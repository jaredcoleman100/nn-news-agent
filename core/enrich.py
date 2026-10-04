"""Fetch the article page for an item the feed delivered as a headline, or as a bare URL.

Two problems this solves:
  * RSS feeds ship titles with little or no summary. Measured on NRK's toppsaker.rss: 23 of 40
    items with an empty body, 57 chars on average. Beat scoring and drafting then run off
    headlines alone, which is why drafts come back full of UNVERIFIED.
  * Sitemap sources (plugins/sources/sitemap.py) yield a URL and a date and nothing else, so
    the title has to come from the page as well.

    ENRICH_BODIES=0      switch it off
    ENRICH_MIN_BODY      only enrich when the body is shorter than this (default 400)
    ENRICH_DELAY         seconds between fetches, politeness (default 1.0)
    ENRICH_ROBOTS=0      stop honouring robots.txt (honoured by default)
    ENRICH_MAX_BODY      cap on stored body text (default 8000)

Never raises: a failed fetch leaves whatever the source gave us in place.
"""
from __future__ import annotations

import os
import re
import time
import urllib.parse
import urllib.robotparser
from functools import lru_cache

import httpx

ENABLED = os.environ.get("ENRICH_BODIES", "1") != "0"
MIN_BODY = int(os.environ.get("ENRICH_MIN_BODY", "400"))
DELAY = float(os.environ.get("ENRICH_DELAY", "1.0"))
RESPECT_ROBOTS = os.environ.get("ENRICH_ROBOTS", "1") != "0"
MAX_BODY = int(os.environ.get("ENRICH_MAX_BODY", "8000"))

UA_TOKEN = "nn-news-agent"
UA = UA_TOKEN + "/0.2 (newsroom monitoring; contact your editor)"
DROP_TAGS = ("script", "style", "noscript", "nav", "aside", "header", "footer",
             "form", "figure", "iframe", "template")
_WS = re.compile(r"\s+")
_last_fetch = 0.0


@lru_cache(maxsize=64)
def _robots(origin: str) -> urllib.robotparser.RobotFileParser | None:
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(origin + "/robots.txt")
    try:
        rp.read()
    except Exception:       # noqa: BLE001 - no robots.txt, or unreachable: do not block on it
        return None
    return rp


def allowed(url: str) -> bool:
    """Honour robots.txt. An unreadable robots.txt is permissive, an explicit disallow is not."""
    if not RESPECT_ROBOTS:
        return True
    parts = urllib.parse.urlsplit(url)
    rp = _robots(parts.scheme + "://" + parts.netloc)
    if rp is None:
        return True
    try:
        return rp.can_fetch(UA_TOKEN, url)
    except Exception:       # noqa: BLE001
        return True


def _fetch_html(url: str) -> str | None:
    """One rate-limited, robots-respecting GET. Returns None on any failure."""
    global _last_fetch
    if not allowed(url):
        print("  enrich: robots.txt disallows " + url)
        return None
    wait = DELAY - (time.monotonic() - _last_fetch)      # one shared limit across all hosts
    if wait > 0:
        time.sleep(wait)
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=20, follow_redirects=True)
        r.raise_for_status()
        return r.text
    except Exception as e:  # noqa: BLE001 - enrichment is best-effort, never fatal
        print("  enrich: " + type(e).__name__ + " on " + url)
        return None
    finally:
        _last_fetch = time.monotonic()


def extract(html_text: str) -> str:
    """Article text: prefer <article>/<main>, and prefer real paragraphs over raw node text."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup(list(DROP_TAGS)):
        tag.decompose()
    node = soup.find("article") or soup.find("main") or soup.body or soup
    paras = [p.get_text(" ", strip=True) for p in node.find_all("p")]
    text = " ".join(p for p in paras if len(p) > 40)     # drop nav crumbs and captions
    if len(text) < 200:                                  # no <p> structure: take the whole node
        text = node.get_text(" ", strip=True)
    return _WS.sub(" ", text).strip()[:MAX_BODY]


def extract_title(html_text: str) -> str:
    """og:title, then <h1>, then <title>. Sitemap items arrive with no title at all."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_text, "html.parser")
    og = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "og:title"})
    if og and og.get("content"):
        return _WS.sub(" ", og["content"]).strip()[:300]
    h1 = soup.find("h1")
    if h1:
        t = _WS.sub(" ", h1.get_text(" ", strip=True)).strip()
        if t:
            return t[:300]
    if soup.title and soup.title.string:
        # strip a trailing " | Outlet" / " - Outlet" suffix
        t = _WS.sub(" ", soup.title.string).strip()
        return re.split(r"\s+[|–—-]\s+", t)[0][:300] or t[:300]
    return ""


def article(url: str, existing_body: str = "", existing_title: str = "") -> dict[str, str]:
    """Return only the fields the page genuinely improves, so a bad fetch overwrites nothing."""
    if not ENABLED or not url:
        return {}
    need_body = len(existing_body or "") < MIN_BODY
    need_title = not (existing_title or "").strip()
    if not (need_body or need_title):
        return {}
    html_text = _fetch_html(url)
    if html_text is None:
        return {}
    out: dict[str, str] = {}
    if need_body:
        text = extract(html_text)
        if len(text) > max(len(existing_body or ""), 200):   # paywall or consent shell
            out["body"] = text
    if need_title:
        title = extract_title(html_text)
        if title:
            out["title"] = title
    return out


def body(url: str, existing: str = "") -> str | None:
    """Back-compat wrapper: just the improved body, or None."""
    return article(url, existing, existing_title="x").get("body")
