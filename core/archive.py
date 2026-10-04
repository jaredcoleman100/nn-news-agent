"""Filesystem archive of fetched news items: one readable file per item, deduped by URL.

The database keeps the canonical row; this keeps a greppable copy the newsroom can read,
diff and keep after a row is pruned. Writes are idempotent, so re-fetching a feed does not
duplicate or rewrite files.

    ITEM_ARCHIVE_DIR   where to write (default <project>/archive/items)
    ITEM_ARCHIVE=0     switch it off entirely

Note: the default sits inside the project, which on a shared drive means every item syncs to
everyone. Point ITEM_ARCHIVE_DIR at local disk if that is not wanted.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENABLED = os.environ.get("ITEM_ARCHIVE", "1") != "0"
ARCHIVE_DIR = Path(os.environ.get("ITEM_ARCHIVE_DIR", str(ROOT / "archive" / "items")))

_NON_WORD = re.compile("[^a-zA-Z0-9]+")

# Separates the source text from its English twin inside an archived item. An HTML comment so it
# renders as nothing in any markdown viewer, and a fixed literal so archive_site can split on it.
EN_MARK = "<!-- en -->"


def _slug(text: str, limit: int = 60) -> str:
    out = _NON_WORD.sub("-", (text or "").strip().lower()).strip("-")
    return out[:limit] or "untitled"


def _day(published_at: Any) -> str:
    """RSS dates are RFC-822 ("Mon, 14 Sep 2026 09:02:12 GMT"), not ISO, so slicing the first
    ten characters yields a comma and a truncated month. Parse both, fall back to today."""
    raw = str(published_at or "").strip()
    for parse in (datetime.fromisoformat, parsedate_to_datetime):
        try:
            return parse(raw).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            continue
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def path_for(item: dict[str, Any]) -> Path:
    """Stable path for an item: bucketed by publication day, named by title + URL hash."""
    day = _day(item.get("published_at"))
    digest = hashlib.sha1(str(item.get("url", "")).encode("utf-8")).hexdigest()[:8]
    return ARCHIVE_DIR / day / (_slug(str(item.get("title", ""))) + "--" + digest + ".md")


def save(item: dict[str, Any], source_name: str = "", overwrite: bool = False,
         org: str = "") -> Path | None:
    """Write one item. Returns the path, or None if archiving is off, unusable or already saved.
    Pass overwrite=True when the body has genuinely improved (enrichment backfill)."""
    if not ENABLED or not item.get("url"):
        return None
    p = path_for(item)
    if p.exists() and not overwrite:    # idempotent: a feed re-poll must not rewrite history
        return None
    fetched = datetime.now(timezone.utc).isoformat()
    body = str(item.get("body") or "").strip()
    # The English twin, when core/translate.py has produced one. Absent on a freshly fetched item
    # -- translation runs after the fetch -- so the file is written monolingual now and rewritten
    # in parallel by sync_archive() once the twin exists. Front matter stays one-line-per-key
    # because archive_site._parse() splits on the first colon and does not read YAML.
    title_en = str(item.get("title_en") or "").replace(chr(10), " ").strip()
    body_en = str(item.get("body_en") or "").strip()
    # json.dumps, not bare text: a double-quoted JSON string is also a valid YAML scalar, and
    # Norwegian headlines are full of colons ("Tromsøball TV: Se intervjuer fra Lerkendal"), which
    # unquoted make the front matter invalid YAML -- `mapping values are not allowed here`. This
    # file's own reader splits on the first colon and never noticed, but any static-site generator
    # pointed at this directory parses it as real YAML and 29% of the archive failed.
    def fm(key: str, value: Any) -> str:
        return key + ": " + json.dumps(str(value or "").replace(chr(10), " "), ensure_ascii=False)

    header = [
        "---",
        fm("title", item.get("title")),
        fm("url", item.get("url")),
        fm("source", source_name or "unknown"),
        # own = this newsroom's outlet (NRK), external = everyone else. The archive index
        # filters on it, and the digest leads on external. See core/outlets.py.
        fm("org", org or "external"),
        fm("lang", item.get("lang")),
        fm("published_at", item.get("published_at")),
        fm("fetched_at", fetched),
    ]
    if title_en:
        header.append(fm("title_en", title_en))
    header += [
        "---",
        "",
        "# " + str(item.get("title") or "(no title)"),
        "",
    ]
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8", newline=chr(10)) as fh:
            fh.write(chr(10).join(header))
            fh.write(body + chr(10))
            # Parallel English below the source text, never instead of it: the source is what the
            # beats are embedded against and what the ethics screens read, so it stays first and
            # verbatim. An item already in English gets no duplicate section.
            if body_en and str(item.get("lang") or "").lower() != "en":
                # EN_MARK, not a "---" rule: archive_site._parse() splits front matter on the
                # first "---" pair and would read a second one as the end of a new document.
                fh.write(chr(10) + EN_MARK + chr(10) * 2)
                fh.write("# " + (title_en or str(item.get("title") or "(no title)")) + chr(10) * 2)
                fh.write(body_en + chr(10))
    except OSError as e:    # a full or read-only archive must never stop the pipeline
        print("  archive: could not write " + p.name + ": " + str(e))
        return None
    return p
