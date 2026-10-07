"""Export drafted reports -- the digests themselves -- for the site build to read.

    archive/reports.json   [{id, newsroom, product, gate, headline, headline_en, body, body_en,
                             created_at, decision, stories: [...]}, ...]

WHY THIS EXISTS
Until now the digest was only ever an email. The site showed the raw archive -- every ingested item,
browsable by category -- but not the one artefact the pipeline exists to produce. So the thing a
reader actually wants ("what happened, in order of importance, with links") lived in an inbox, and
the thing nobody asked for (7,589 scraped items) was the front page.

This inverts that. The digest leads; the archive is what you click into.

WHAT A `story` IS
Each claim in a report names a source_url. Joined back to `items` that gives the headline, its
English translation, the outlet and whether the outlet is this newsroom's own (NRK) or outside it.
That join is the whole point of the page: a summary sentence in two languages, attributed to a
named outlet, linking to the original. Claims are grouped by URL, because one article commonly
supports two or three claims and rendering it twice reads as an editing mistake.

WHAT IS DELIBERATELY NOT EXPORTED
Item bodies. Not `body`, not `body_en`. The export carries our own summary sentences plus the
source's headline, and nothing else of the source's text -- which is what makes the digest pages
safe to host publicly when the item pages are not. See core/publish.py's PUBLIC note.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from core.archive import ARCHIVE_DIR
from core import outlets

REPORTS_FILE = Path(os.environ.get("ARCHIVE_REPORTS", str(ARCHIVE_DIR.parent / "reports.json")))

# How many digests the site keeps pages for. Every one ever drafted, in practice -- 13 today, one
# per weekday, so this is a guard against an accident rather than a real limit.
LIMIT = int(os.environ.get("ARCHIVE_REPORTS_LIMIT", "400"))


def _items_by_url(sb, urls: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Look up every cited article in chunks, keeping EVERY row that carries a given URL.

    `in_` on 200 URLs at a time: PostgREST puts the list in the query string, and Norwegian URLs
    are long enough that a few hundred approaches the limit a proxy will accept.

    A list rather than one row per URL, because the same article genuinely exists twice: NRK
    Nordland and NRK Troms og Finnmark syndicate the same piece, and a revised headline creates a
    second row. Only one of the two is usually scored, so keeping "whichever arrived last" lost
    the categories for 21 of 109 cited stories -- they looked uncategorised when they were not.
    """
    out: dict[str, list[dict[str, Any]]] = {}
    for chunk in _url_chunks(urls):
        rows = (sb.table("items")
                .select("id,url,title,title_en,title_nb,lang,source_id,published_at")
                .in_("url", chunk).execute().data)
        for row in rows:
            out.setdefault(row["url"], []).append(row)
    return out


# PostgREST puts `in_` values in the QUERY STRING, so the limit that matters is the length of the
# URL, not the number of values. A fixed chunk of 200 was fine while every source was a newspaper
# with ~90-character links; Google News aggregator links are ~450 characters of base64 redirect,
# so 200 of them built an 80 KB request and the server answered 400 "JSON could not be generated"
# -- an error that names neither the cause nor the query. Budget the characters instead.
_MAX_QUERY_CHARS = 12000


def _url_chunks(urls: list[str]) -> list[list[str]]:
    """Group URLs so no single `in_` filter exceeds what the server will accept."""
    chunks: list[list[str]] = []
    batch: list[str] = []
    size = 0
    for url in urls:
        n = len(url) + 3                      # quotes and comma, url-encoded
        if batch and size + n > _MAX_QUERY_CHARS:
            chunks.append(batch)
            batch, size = [], 0
        batch.append(url)
        size += n
    if batch:
        chunks.append(batch)
    return chunks


CITED_FILE = Path(os.environ.get("ARCHIVE_CITED", str(ARCHIVE_DIR.parent / "cited.json")))


def _load_cited() -> dict[str, dict[str, Any]]:
    """Titles of articles a brief has cited, remembered across exports.

    WHY THIS EXISTS
    A card's title and outlet were read from `items` at export time, every time. Items leave that
    table -- 24 cited URLs had gone by 2026-10-07 -- and when one did, its card lost its headline
    and its outlet and fell back to printing the raw URL. The brief still quoted the article; the
    page just stopped being able to say which article it was.

    The archive is derived and may be rebuilt, but a citation is a published claim about a specific
    piece of someone else's journalism, and it has to stay attributable for as long as the brief is
    up. So the first time a cited URL resolves, its title and outlet are written here, and from then
    on the card survives the item being deleted, re-ingested or aged out.

    Append-only in practice: an entry is refreshed while the item exists and kept once it does not.
    Small -- a few hundred rows of titles -- and committed, so a CI build has it too.
    """
    try:
        return json.loads(CITED_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_cited(cited: dict[str, dict[str, Any]]) -> None:
    CITED_FILE.parent.mkdir(parents=True, exist_ok=True)
    CITED_FILE.write_text(json.dumps(cited, ensure_ascii=False, indent=1, sort_keys=True),
                          encoding="utf-8")


def _best(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The row to display for a URL: prefer a translated one, then one with a title at all."""
    if not rows:
        return {}
    return sorted(rows, key=lambda r: (bool(r.get("title_en")), bool(r.get("title_nb")),
                                       bool(r.get("title"))), reverse=True)[0]


# Aggregator feed names are not outlets. A Google News query feed is called
# "Google News 中文: 北极 / 挪威"; the journalism in it was done by HK01, Xinhua or Yahoo Japan,
# and those names are carried in the item title as a " - Outlet" suffix. Crediting the aggregator
# on a card is wrong on a page whose whole premise is pointing at other people's reporting.
_AGGREGATOR = "news.google.com"


def _outlet_of(item: dict[str, Any], src: dict[str, Any]) -> tuple[str, str]:
    """(outlet, title) for a card. Splits the publisher out of an aggregator item's title."""
    name = src.get("name") or ""
    title = str(item.get("title") or "")
    if _AGGREGATOR not in str(src.get("url") or ""):
        return name, title
    # Feed titles read "Headline text - Publisher". Split on the LAST such separator: headlines
    # contain dashes, publisher names very rarely do.
    at = title.rfind(" - ")
    if at > 0 and len(title) - at < 60:
        return title[at + 3:].strip(), title[:at].strip()
    return name, title


def _merge_cats(rows: list[dict[str, Any]],
                cats_of: dict[int, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Every category any row for this URL matched, strongest score per category kept."""
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        for cat in cats_of.get(row["id"]) or []:
            keep = best.get(cat["key"])
            if keep is None or cat["score"] > keep["score"]:
                best[cat["key"]] = cat
    return sorted(best.values(), key=lambda c: -c["score"])


_ENTITIES: list[str] | None = None


def _entities() -> list[str]:
    """The gazetteer, longest first so «Øst-Finnmark» wins over «Finnmark»."""
    global _ENTITIES
    if _ENTITIES is None:
        try:
            raw = json.loads((ARCHIVE_DIR.parents[1] / "config" / "nord-norge" /
                              "entities.json").read_text(encoding="utf-8"))
            _ENTITIES = sorted(raw.get("entities") or [], key=len, reverse=True)
        except (OSError, json.JSONDecodeError):
            _ENTITIES = []
    return _ENTITIES


def _entity_of(title: str) -> str:
    """The one entity a story may be illustrated with, or "" for none."""
    hay = (title or "").lower()
    for e in _entities():
        if e.lower() in hay:
            return e
    return ""


def export(sb) -> Path:
    """Write archive/reports.json. Returns the path."""
    reports = (sb.table("reports")
               .select("id,newsroom_id,product_id,gate,headline,body,sections,claims,"
                       "screen_result,editor_decision,created_at")
               .order("created_at", desc=True).limit(LIMIT).execute().data)

    urls = sorted({(c or {}).get("source_url") or ""
                   for r in reports for c in (r.get("claims") or [])} - {""})
    items = _items_by_url(sb, urls)
    cited = _load_cited()

    # Outlet display names come from `sources`, so a card says "Altaposten" rather than a slug.
    srcs = {s["id"]: s for s in sb.table("sources").select("id,name,url,config").execute().data}

    # The beats each cited article matched, so the briefs can be browsed by category.
    #
    # Read from `hits` rather than from archive/hits.json: that file is keyed to the archive tree,
    # which the public build deliberately does not read at all. Going to the same table the export
    # comes from keeps the two builds agreeing about which category a story is in. 105 of 109
    # cited articles carry at least one beat; the four that do not were cited from outside the
    # scored window, and simply have no category.
    beats = {(b["newsroom_id"], b["id"]): b["name"]
             for b in sb.table("beats").select("id,name,newsroom_id").execute().data}
    cats_of: dict[int, list[dict[str, Any]]] = {}
    item_ids = sorted({r["id"] for rows in items.values() for r in rows})
    for i in range(0, len(item_ids), 200):
        chunk = item_ids[i:i + 200]
        for h in (sb.table("hits").select("item_id,beat_id,newsroom_id,score")
                  .in_("item_id", chunk).execute().data):
            name = beats.get((h["newsroom_id"], h["beat_id"]))
            if not name:
                continue
            cats_of.setdefault(h["item_id"], []).append({
                # Same key shape as site/_data/categories.js builds, so a category means the same
                # thing on both surfaces.
                "key": f"{h['newsroom_id']}-{h['beat_id']}",
                "name": name,
                "newsroom": h["newsroom_id"],
                "score": round(float(h.get("score") or 0), 4),
            })
    for cats in cats_of.values():
        cats.sort(key=lambda c: -c["score"])

    out = []
    for r in reports:
        sections = r.get("sections") or {}
        # Group claims by the article they rest on: one card per source, with the claims it
        # supports listed under it.
        grouped: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for claim in (r.get("claims") or []):
            url = (claim or {}).get("source_url") or ""
            text = (claim or {}).get("claim") or ""
            if not text:
                continue
            if url not in grouped:
                rows = items.get(url) or []
                item = _best(rows)
                src = srcs.get(item.get("source_id")) or {}
                outlet, display_title = _outlet_of(item, src)

                # Remember it while we can; fall back to what we remembered when we cannot. See
                # _load_cited(). An item that has left `items` resolves to {} above, which used to
                # mean a card with no headline and no outlet.
                if display_title or item.get("title_en"):
                    cited[url] = {"title": display_title,
                                  "title_en": item.get("title_en") or "",
                                  "title_nb": item.get("title_nb") or "",
                                  "lang": (item.get("lang") or "").lower(),
                                  "source": outlet or item.get("source_id") or ""}
                elif url in cited:
                    remembered = cited[url]
                    display_title = remembered.get("title") or ""
                    item = {**item, **{k: remembered.get(k, "")
                                       for k in ("title_en", "title_nb", "lang")}}
                    outlet = outlet or remembered.get("source") or ""

                grouped[url] = {
                    "url": url,
                    "title": display_title,
                    "title_en": item.get("title_en") or "",
                    # Norwegian rendering of a non-Norwegian source. Empty for a Norwegian source,
                    # where `title` already IS the Norwegian text and the template falls back.
                    "title_nb": item.get("title_nb") or "",
                    "lang": (item.get("lang") or "").lower(),
                    "source": outlet or item.get("source_id") or "",
                    # The feed it arrived through, kept so an aggregator item can still be traced
                    # back to the query that found it.
                    "via": (src.get("name") or "") if outlet != (src.get("name") or "") else "",
                    # own = NRK, external = everyone else. The digest's whole editorial premise is
                    # that these are different things, so the card has to say which it is.
                    # When the source row is missing (an item whose source was deleted) fall
                    # back to the article URL itself, so the NRK/outside split cannot silently
                    # default every orphan to "outside NRK" -- the half that leads the digest.
                    "org": outlets.org_of(src or {"url": url}),
                    # Where the OUTLET sits, not what the story is about. Set per source in
                    # sources.json; "global" for an aggregator that is multi-origin by design.
                    "region": (src.get("config") or {}).get("region") or "global",
                    "published_at": item.get("published_at") or "",
                    # At most one, and it illustrates the ENTITY, not the event.
                    "entity": _entity_of(display_title),
                    # Union across every row sharing this URL: the scored copy is often not
                    # the one with the better title, so taking cats from the display row
                    # alone would drop the category.
                    "cats": _merge_cats(rows, cats_of),
                    "claims": [],
                }
                order.append(url)
            grouped[url]["claims"].append(text)

        # Every flag, including `note`. The site no longer withholds a brief because the screens
        # fired (2026-09-28, by instruction); it publishes and says what was flagged. `note` is the
        # AI-disclosure flag, which carries NRK-KI and VVP 3.2/4.11 and is on all fifteen briefs --
        # exactly the thing a reader is entitled to see rather than have filtered out of the data.
        flags = ((r.get("screen_result") or {}).get("ethics") or {}).get("flags") or []

        out.append({
            "id": r["id"],
            "newsroom": r.get("newsroom_id") or "",
            "product": r.get("product_id") or "",
            "gate": r.get("gate") or "",
            "headline": r.get("headline") or "",
            "headline_en": sections.get("headline_en") or "",
            "body": r.get("body") or "",
            "body_en": sections.get("body_en") or "",
            "created_at": r.get("created_at") or "",
            "decision": r.get("editor_decision") or "",
            "flags": [{
                "flag": f.get("flag"),
                "severity": f.get("severity"),
                "clauses": f.get("clauses") or [],
                # The matched token. Published pages do not render it -- the screens are regex and
                # the matches are frequently the wrong word ("minoriteter" tripping a
                # minor-involved rule, "kritiserer" tripping a right-of-reply rule), so showing it
                # to a reader would be noise dressed as disclosure. The internal build does show
                # it, because there it is the only thing that explains why a flag fired.
                "evidence": f.get("evidence") or [],
            } for f in flags],
            "stories": [grouped[u] for u in order],
        })

    REPORTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORTS_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8",
                            newline="\n")
    _save_cited(cited)
    orphans = sum(1 for r in out for s in r["stories"] if not (s["title"] or s["title_en"]))
    stories = sum(len(r["stories"]) for r in out)
    en = sum(1 for r in out if r["body_en"])
    keys = {c["key"] for r in out for s in r["stories"] for c in s["cats"]}
    uncat = sum(1 for r in out for s in r["stories"] if not s["cats"])
    print(f"  reports export: {len(out)} digests, {stories} cited stories, {en} with English, "
          f"{len(keys)} categories ({uncat} stories uncategorised) -> {REPORTS_FILE.name}")
    print(f"  cited cache: {len(cited)} articles remembered"
          + (f", {orphans} cards still have no title" if orphans else ", every card has a title"))
    return REPORTS_FILE


# ---------------------------------------------------------------- pipeline facts for the reader

PIPELINE_FILE = Path(os.environ.get("ARCHIVE_PIPELINE",
                                    str(ARCHIVE_DIR.parent / "pipeline.json")))


def export_pipeline(sb) -> Path:
    """Write archive/pipeline.json: what the explainer page tells the reader about this desk.

    Measured, not typed. Every figure on that page -- how many sources, how many languages, how
    much of the intake becomes a hit -- is a number that rots within days, and a page describing
    a monitoring system inaccurately is worse than no page. The one hardcoded figure in the
    architecture document ("eleven tables", when there were twelve) is why this is an export.
    """
    srcs = [s for s in sb.table("sources").select("name,url,active,config").execute().data
            if s.get("active")]
    # Sources with no `lang` are the scholarly APIs -- OpenAlex, Cristin, EuropePMC -- which are
    # query endpoints, not language feeds. Counting them as a language called "und" put a chip
    # reading "und" on the explainer page and inflated the language count by one.
    langs: dict[str, int] = {}
    scholarly = 0
    for s in srcs:
        code = (s.get("config") or {}).get("lang")
        if not code:
            scholarly += 1
            continue
        langs[code] = langs.get(code, 0) + 1

    items = sb.table("items").select("id", count="exact", head=True).execute().count or 0
    hits = sb.table("hits").select("id", count="exact", head=True).execute().count or 0
    translated = (sb.table("items").select("id", count="exact", head=True)
                  .not_.is_("title_en", "null").execute().count or 0)

    out = {
        "sources": len(srcs),
        "languages": sorted(langs.items(), key=lambda kv: (-kv[1], kv[0])),
        "language_count": len(langs),
        "scholarly": scholarly,
        "items": items,
        "hits": hits,
        "hit_pct": round(100 * hits / items, 1) if items else 0.0,
        "translated": translated,
        "translated_pct": round(100 * translated / items, 1) if items else 0.0,
        # Named, so the page can say whose journalism it is pointing at rather than "various".
        "outlets": sorted({s["name"] for s in srcs}),
    }
    PIPELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PIPELINE_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8",
                            newline="\n")
    print(f"  pipeline export: {out['sources']} sources, {out['language_count']} languages, "
          f"{out['items']:,} items, {out['hit_pct']}% hit rate -> {PIPELINE_FILE.name}")
    return PIPELINE_FILE
