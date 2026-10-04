"""SourceAdapter for outlets that publish no feed but do publish a dated sitemap.

The Barents Observer and High North News are the two most on-beat outlets for Nord-Norge and
neither exposes RSS at any path; both are client-rendered. Both do serve /sitemap.xml with
<lastmod> on every URL, which is enough: this adapter yields url + published_at, and
core/enrich.py fills in the title and body from the article page.

Per-source options live in `sources.config` (jsonb):
    days     only URLs modified within this many days   (default 4)
    limit    cap on items returned per poll             (default 25)
    include  regex a URL must match   e.g. "/news/"     (default: any)
    exclude  regex a URL must not match e.g. "/meninger/|/livet-i-arktis/"
    sub      max sub-sitemaps to read from an index     (default 2)

The include/exclude filters matter: High North News publishes opinion (/meninger/) and sport
alongside news, and a monitor must not draft reports on either.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from core.registry import register

UA = {"User-Agent": "nn-news-agent/0.2 (newsroom monitoring)"}
URL_RE = re.compile(r"<url>(.*?)</url>", re.S)
LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
MOD_RE = re.compile(r"<(?:lastmod|news:publication_date)>\s*([^<\s]+)")


def _parse_dt(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    for candidate in (raw, raw.replace("Z", "+00:00")):
        try:
            d = datetime.fromisoformat(candidate)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _entries(xml: str) -> list[tuple[str, datetime | None]]:
    """(loc, lastmod) pairs. Falls back to positional pairing for flat sitemaps."""
    out: list[tuple[str, datetime | None]] = []
    blocks = URL_RE.findall(xml)
    if blocks:
        for b in blocks:
            loc = LOC_RE.search(b)
            if loc:
                mod = MOD_RE.search(b)
                out.append((loc.group(1), _parse_dt(mod.group(1)) if mod else None))
        return out
    locs = LOC_RE.findall(xml)
    mods = MOD_RE.findall(xml)
    for i, loc in enumerate(locs):
        out.append((loc, _parse_dt(mods[i]) if i < len(mods) else None))
    return out


class SitemapSource:
    name = "sitemap"

    def _get(self, url: str) -> str:
        r = httpx.get(url, headers=UA, timeout=30, follow_redirects=True)
        r.raise_for_status()
        return r.text

    def fetch(self, source: dict[str, Any], since: str | None) -> list[dict[str, Any]]:
        cfg = source.get("config") or {}
        days = int(cfg.get("days", 4))
        limit = int(cfg.get("limit", 25))
        sub_max = int(cfg.get("sub", 2))
        include = re.compile(cfg["include"]) if cfg.get("include") else None
        exclude = re.compile(cfg["exclude"]) if cfg.get("exclude") else None

        xml = self._get(source["url"])
        rows = _entries(xml)

        # A sitemap index lists further sitemaps; read the most recently modified ones.
        if rows and all(loc.rstrip("/").endswith(".xml") or "sitemap" in loc for loc, _ in rows[:3]):
            rows.sort(key=lambda x: (x[1] or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
            merged: list[tuple[str, datetime | None]] = []
            for loc, _ in rows[:sub_max]:
                try:
                    merged += _entries(self._get(loc))
                except Exception:   # noqa: BLE001 - one bad sub-sitemap must not kill the poll
                    continue
            rows = merged

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        keep: list[tuple[str, datetime]] = []
        for loc, mod in rows:
            if mod is None or mod < cutoff:
                continue
            if include and not include.search(loc):
                continue
            if exclude and exclude.search(loc):
                continue
            keep.append((loc, mod))

        keep.sort(key=lambda x: x[1], reverse=True)
        # title and body are left empty on purpose: core/enrich.py fills both from the page.
        return [{"url": loc, "title": "", "body": "", "published_at": mod.isoformat()}
                for loc, mod in keep[:limit]]


register("source", SitemapSource())
