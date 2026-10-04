"""SourceAdapter for scholarly literature affecting Nord-Norge.

Three backends, all free and keyless, selected per source via `sources.config.api`:

    openalex    api.openalex.org       all disciplines, date-sortable, abstracts included
    cristin     api.cristin.no         the Norwegian research registry: UiT / Nord University
                                       output that never reaches a news feed
    europepmc   ebi.ac.uk/europepmc    biomedical, for helse-nord and Sámi health research

Config keys: api, query, days (default 30), limit (default 10), min_body, require.

Two precision guards, both learned from the first live run:
  * `min_body` (default 300) drops records with no usable abstract. Cristin returns LECTURE,
    THESISMASTER and MEDIAINTERVIEW entries with a 19-character summary; drafting from those
    reproduces exactly the headline-only problem enrichment was built to fix.
  * `require` (default: a Nord-Norge / Arctic region pattern) drops off-region hits. Keyword
    search is not region-bound: "reindeer herding wind power land use conflict" returned work
    on mountain caribou in British Columbia, which would become a false hit under trust_hint.

Crossref is deliberately not implemented: sorting it by date discards relevance entirely — a
"Sámi reindeer herding" query returned Clostridium and tuberculosis papers — so it would need
a different query strategy to be safe. arXiv rate-limits aggressively (429) and needs its own
backoff before it belongs in an hourly poll.

Abstracts are returned as the item body, so these items are NOT enriched further: an abstract
is the citable unit, and fetching publisher pages would often hit a paywall.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from core.registry import register

UA = {"User-Agent": "nn-news-agent/0.2 (newsroom monitoring; contact your editor)"}

# Default region guard. Keyword search reaches the whole circumpolar literature, and this
# newsroom covers one part of it.
REGION = re.compile(
    r"norw|norge|norsk|svalbard|spitsbergen|barents|s[aá]pmi|sami|s[aá]mi|saami|"
    r"finnmark|troms|nordland|kola|murmansk|longyearbyen|kirkenes|tromso|tromsø|"
    r"arctic norway|high north|nordomr",
    re.I)


_PUNCT = re.compile(r"[^a-z0-9]+")


def _dedup(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One work per normalised title. OpenAlex lists the preprint and the published version as
    separate records with different URLs, so URL-level dedup in the DB never catches them.
    Prefer the peer-reviewed version, then the fuller abstract."""
    best: dict[str, dict[str, Any]] = {}
    for i in items:
        key = _PUNCT.sub(" ", (i.get("title") or "").lower()).strip()
        if not key:
            continue
        prev = best.get(key)
        if prev is None:
            best[key] = i
            continue
        pre_new = "preprint" in (i.get("body") or "")[:60].lower()
        pre_old = "preprint" in (prev.get("body") or "")[:60].lower()
        if (pre_old and not pre_new) or (pre_old == pre_new
                                         and len(i.get("body") or "") > len(prev.get("body") or "")):
            best[key] = i
    return list(best.values())


def _openalex_abstract(inv: dict[str, list[int]] | None) -> str:
    """OpenAlex ships abstracts as an inverted index {word: [positions]}."""
    if not inv:
        return ""
    pairs: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            pairs.append((i, word))
    pairs.sort()
    return " ".join(w for _, w in pairs)


class ScholarlySource:
    name = "scholarly"

    def _get(self, url: str, params: dict[str, Any]) -> Any:
        r = httpx.get(url, params=params, headers=UA, timeout=30, follow_redirects=True)
        r.raise_for_status()
        return r.json()

    # ---------------------------------------------------------------- backends
    def _openalex(self, query: str, days: int, limit: int) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        data = self._get("https://api.openalex.org/works", {
            "search": query, "sort": "publication_date:desc", "per-page": limit,
            "filter": "from_publication_date:" + since})
        out = []
        for w in data.get("results", []):
            loc = w.get("primary_location") or {}
            url = loc.get("landing_page_url") or w.get("doi") or w.get("id")
            if not url:
                continue
            abstract = _openalex_abstract(w.get("abstract_inverted_index"))
            venue = ((loc.get("source") or {}).get("display_name")) or "ukjent tidsskrift"
            kind = w.get("type") or "article"
            out.append({
                "url": url,
                "title": (w.get("title") or "").strip(),
                "body": f"[{kind}, {venue}] " + abstract,
                "published_at": w.get("publication_date") or "",
            })
        return out

    def _cristin(self, query: str, days: int, limit: int,
                 category: str = "ARTICLE") -> list[dict[str, Any]]:
        # Cristin exposes only year_published, so `days` degrades to a year filter.
        #
        # Two measured traps. Without a category filter the results are dominated by LECTURE,
        # MEDIAINTERVIEW, POSTER and THESISMASTER records, none of which carry a summary. And
        # Cristin's Norwegian-language records largely have no abstract either, while its
        # English-language ones do: title="samisk" + ARTICLE gave 0 of 9 with a usable
        # abstract, title="sami" gave 7 of 10 and "Svalbard" 9 of 10. So query Cristin in
        # English even for Norwegian subject matter; it still returns Norwegian-registered work.
        year = (datetime.now(timezone.utc) - timedelta(days=days)).year
        params = {"title": query, "per_page": limit, "published_since": year,
                  "sort": "year_published desc"}
        if category:
            params["category"] = category
        data = self._get("https://api.cristin.no/v2/results", params)
        out = []
        for it in data if isinstance(data, list) else []:
            titles = it.get("title") or {}
            title = titles.get("no") or titles.get("en") or next(iter(titles.values()), "")
            rid = it.get("cristin_result_id")
            if not (title and rid):
                continue
            summary = it.get("summary") or {}
            abstract = summary.get("no") or summary.get("en") or ""
            journal = ((it.get("journal") or {}).get("name")) or "Cristin"
            out.append({
                "url": "https://app.cristin.no/results/show.jsf?id=" + str(rid),
                "title": str(title).strip(),
                "body": f"[{it.get('category', {}).get('code', 'publication')}, {journal}] " + abstract,
                "published_at": str(it.get("year_published") or "") + "-01-01",
            })
        return out

    def _europepmc(self, query: str, days: int, limit: int) -> list[dict[str, Any]]:
        data = self._get("https://www.ebi.ac.uk/europepmc/webservices/rest/search", {
            "query": query, "format": "json", "pageSize": limit,
            "sort": "P_PDATE_D desc", "resultType": "core"})
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        out = []
        for it in (data.get("resultList") or {}).get("result", []):
            pub = it.get("firstPublicationDate") or ""
            if pub and pub < cutoff:
                continue
            src, pid = it.get("source"), it.get("id")
            if not (src and pid):
                continue
            peer = "peer-reviewed" if it.get("source") != "PPR" else "PREPRINT, not peer-reviewed"
            venue = (it.get("journalTitle")
                     or (((it.get("journalInfo") or {}).get("journal") or {}).get("title"))
                     or it.get("bookOrReportDetails", {}).get("publisher")
                     or "ukjent tidsskrift")
            out.append({
                "url": "https://europepmc.org/article/" + str(src) + "/" + str(pid),
                "title": (it.get("title") or "").strip().rstrip("."),
                # resultType=core nests the venue; journalTitle is only set for some records
                "body": f"[{peer}, {venue}] " + (it.get("abstractText") or ""),
                "published_at": pub,
            })
        return out

    # ---------------------------------------------------------------- adapter
    def fetch(self, source: dict[str, Any], since: str | None) -> list[dict[str, Any]]:
        cfg = source.get("config") or {}
        api = (cfg.get("api") or "openalex").lower()
        query = cfg.get("query") or ""
        days = int(cfg.get("days", 30))
        limit = int(cfg.get("limit", 10))
        if not query:
            return []
        fn = {"openalex": self._openalex, "cristin": self._cristin,
              "europepmc": self._europepmc}.get(api)
        if fn is None:
            raise KeyError("unknown scholarly api " + api + "; have openalex, cristin, europepmc")
        kwargs = {"category": cfg["category"]} if (api == "cristin" and "category" in cfg) else {}
        min_body = int(cfg.get("min_body", 300))
        require = re.compile(cfg["require"], re.I) if cfg.get("require") else REGION
        out = []
        for i in fn(query, days, limit, **kwargs):
            if not i.get("title"):
                continue
            if len(i.get("body") or "") < min_body:
                continue                      # no usable abstract: nothing to draft from
            if not require.search(i["title"] + " " + i["body"]):
                continue                      # off-region: keyword search is not geofenced
            out.append(i)
        return _dedup(out)


register("source", ScholarlySource())
