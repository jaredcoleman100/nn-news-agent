"""Entity images from Wikimedia Commons, with the attribution their licences require.

    archive/images.json   {entity: {src, width, height, artist, license, license_url, file_page,
                                    descr, fetched_at}}

WHAT THIS IS AND IS NOT
It is NOT press photography of the news. Openly licensed photographs of events from the last few
days barely exist, and the few that do are usually the wrong thing anyway. What Commons has in
abundance is EVERGREEN pictures: a town, a fjord, a parliament building, a politician at some
earlier occasion, a ship, an institution's headquarters.

So the rule this module exists to enforce: an image here illustrates an ENTITY a story names, not
the event the story reports. The site must caption it that way -- the picture is context, and
saying otherwise with a picture is as much a false claim as saying it in words.

ATTRIBUTION IS NOT OPTIONAL
CC BY and CC BY-SA require the author and the licence wherever the work appears. Public-domain
files do not, but Commons asks for the source anyway and it costs nothing. Every record keeps the
artist, the licence name, a link to the licence and a link to the Commons file page, and the
renderer shows them. A file whose licence cannot be read, or which is not free, is skipped -- an
image is never worth guessing about.

    PYTHONPATH=. python run.py --images        resolve any unresolved entities, write the cache
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from core.archive import ARCHIVE_DIR

IMAGES_FILE = Path(os.environ.get("ARCHIVE_IMAGES", str(ARCHIVE_DIR.parent / "images.json")))

# Wikipedia for "what is the lead image of this subject", Commons for "who made it and under what".
WP = "https://no.wikipedia.org/w/api.php"
COMMONS = "https://commons.wikimedia.org/w/api.php"
# Wikimedia asks for a User-Agent that identifies the tool AND gives a way to reach whoever
# runs it. "contact via repo" is not that, and the first run earned a wall of 429s.
UA = ("nn-news-agent/0.2 (Royal News of Norway newsroom monitor; "
      "https://norway-royal-news.pages.dev)")

# Licences we will publish. Anything else -- fair-use tags, non-commercial, no-derivatives, or a
# field we cannot parse -- is skipped rather than guessed at.
FREE = re.compile(
    r"\b(cc[ -]?by(?:[ -]sa)?(?:[ -][0-9.]+)?|cc0|public domain|pd-|gfdl)\b", re.I)


def _api(url: str, params: dict[str, str], tries: int = 4) -> dict[str, Any]:
    """One API call, backing off on 429.

    Commons is free infrastructure and will throttle a client that behaves badly. It throttled
    this one on its first run: too fast, and with a User-Agent that gave no way to contact anyone.
    Both are fixed; this is the belt as well as the braces.
    """
    q = urllib.parse.urlencode({**params, "format": "json", "formatversion": "2"})
    req = urllib.request.Request(f"{url}?{q}", headers={"User-Agent": UA})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as ex:
            if ex.code not in (429, 503) or attempt == tries - 1:
                raise
            wait = float(ex.headers.get("retry-after") or 0) or (2 ** attempt) * 2.0
            time.sleep(min(wait, 30.0))
    raise RuntimeError("unreachable")


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text or "")).strip()


def _lead_image(entity: str) -> tuple[str, str] | None:
    """(file title, page url) of the subject's lead image on Norwegian Wikipedia."""
    d = _api(WP, {"action": "query", "prop": "pageimages|info", "inprop": "url",
                  "piprop": "name", "titles": entity, "redirects": "1"})
    for page in (d.get("query", {}).get("pages") or []):
        name = page.get("pageimage")
        if name:
            return f"File:{name}", page.get("fullurl", "")
    return None


def _commons_meta(file_title: str) -> dict[str, Any] | None:
    d = _api(COMMONS, {"action": "query", "prop": "imageinfo",
                       "iiprop": "url|extmetadata", "iiurlwidth": "900",
                       "titles": file_title})
    for page in (d.get("query", {}).get("pages") or []):
        for info in (page.get("imageinfo") or []):
            ex = info.get("extmetadata") or {}
            def val(k: str) -> str:
                return _strip_html(((ex.get(k) or {}).get("value")) or "")
            licence = val("LicenseShortName") or val("License")
            if not licence or not FREE.search(licence):
                return None                      # not demonstrably free -> do not publish
            return {
                "src": info.get("thumburl") or info.get("url"),
                "width": info.get("thumbwidth") or info.get("width"),
                "height": info.get("thumbheight") or info.get("height"),
                "artist": val("Artist") or "Ukjent / Unknown",
                "license": licence,
                "license_url": val("LicenseUrl"),
                "file_page": info.get("descriptionurl") or "",
                "descr": val("ImageDescription")[:200],
            }
    return None


def resolve(entities: list[str], sleep: float = 1.2) -> dict[str, dict[str, Any]]:
    """Look up each entity, keeping only files under a licence we can publish."""
    out: dict[str, dict[str, Any]] = {}
    for name in entities:
        try:
            found = _lead_image(name)
            if not found:
                continue
            time.sleep(sleep)                     # Commons is free; do not hammer it
            meta = _commons_meta(found[0])
            if not meta or not meta.get("src"):
                continue
            out[name] = {**meta, "entity": name, "subject_page": found[1],
                         "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        except Exception as ex:                   # noqa: BLE001 - one bad lookup is not a failure
            print(f"  images: {name}: {type(ex).__name__}: {str(ex)[:70]}")
        time.sleep(sleep)
    return out


def export(entities: list[str]) -> Path:
    """Resolve any entity not already cached and write archive/images.json."""
    cache: dict[str, Any] = {}
    if IMAGES_FILE.exists():
        try:
            cache = json.loads(IMAGES_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cache = {}
    missing = [e for e in entities if e not in cache]
    if missing:
        cache.update(resolve(missing))
    IMAGES_FILE.parent.mkdir(parents=True, exist_ok=True)
    IMAGES_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8",
                           newline="\n")
    print(f"  images: {len(cache)} entities cached "
          f"({len(missing)} looked up, {len(missing) - (len(cache) - (len(cache) - len(missing)))} "
          f"new) -> {IMAGES_FILE.name}")
    return IMAGES_FILE
