"""RSS SourceAdapter for the Python side (the Edge Function does the same in Deno for the hourly poll)."""
from __future__ import annotations
from typing import Any
import httpx, feedparser  # pip install feedparser
from core.registry import register


class RSS:
    name = "rss"
    def fetch(self, source: dict[str, Any], since: str | None) -> list[dict[str, Any]]:
        r = httpx.get(source["url"], headers={"User-Agent": "nn-news-agent/0.2"}, timeout=20,
                     follow_redirects=True)
        r.raise_for_status()   # a 404 feed must not look like an empty one
        xml = r.text
        out = []
        for e in feedparser.parse(xml).entries:
            out.append({"url": e.get("link"), "title": e.get("title", ""),
                        "body": e.get("summary", ""), "published_at": e.get("published") or e.get("updated")})
        return out


register("source", RSS())
