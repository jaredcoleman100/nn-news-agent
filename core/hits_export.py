"""Export scored hits, joined to their beat and item URL, for the site build to read.

    archive/hits.json   [{url, newsroom, beat, beat_name, score, created_at}, ...]

Why a JSON export rather than beats in the archive front matter: hits move independently of items.
A threshold retune or a `rebuild_hits()` run changes which items are hits without changing a single
item, and writing beats into front matter would mean rewriting 2400 files to reflect that. The
export is regenerated on every publish and costs one small file.

Why URL as the join key: the archive names files by a hash of the URL, and the markdown carries the
URL in front matter, so the site can join without knowing database ids.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from core.archive import ARCHIVE_DIR

HITS_FILE = Path(os.environ.get("ARCHIVE_HITS", str(ARCHIVE_DIR.parent / "hits.json")))
PAGE = 1000


def _all(query_factory) -> list[dict[str, Any]]:
    """Page through PostgREST. An unbounded select silently caps at 1000 rows and returns them
    without complaint, which is invisible until the table crosses that line."""
    out: list[dict[str, Any]] = []
    page = 0
    while True:
        got = query_factory().range(page * PAGE, page * PAGE + PAGE - 1).execute().data
        out += got
        if len(got) < PAGE:
            return out
        page += 1


def export(sb) -> Path:
    """Write archive/hits.json. Returns the path."""
    beats = {(b["newsroom_id"], b["id"]): b
             for b in sb.table("beats").select("id,name,newsroom_id,active").execute().data}
    hits = _all(lambda: sb.table("hits")
                .select("item_id,beat_id,score,status,created_at,newsroom_id").order("id"))

    # Only the items that actually hit -- 229 of 2423 today, so fetching every item would be waste.
    ids = sorted({h["item_id"] for h in hits})
    urls: dict[int, str] = {}
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        for row in sb.table("items").select("id,url").in_("id", chunk).execute().data:
            urls[row["id"]] = row["url"]

    out = []
    for h in hits:
        beat = beats.get((h["newsroom_id"], h["beat_id"]))
        url = urls.get(h["item_id"])
        if not beat or not url:
            continue                    # a hit whose beat or item has since gone
        out.append({
            "url": url,
            "newsroom": h["newsroom_id"],
            "beat": h["beat_id"],
            "beat_name": beat["name"],
            "score": round(float(h.get("score") or 0), 4),
            "status": h.get("status") or "new",
            "created_at": h.get("created_at") or "",
        })

    HITS_FILE.parent.mkdir(parents=True, exist_ok=True)
    HITS_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8",
                         newline="\n")
    desks = {}
    for h in out:
        desks[h["newsroom"]] = desks.get(h["newsroom"], 0) + 1
    print(f"  hits export: {len(out)} hits across {len({(h['newsroom'], h['beat']) for h in out})} "
          f"categories ({', '.join(f'{k} {v}' for k, v in sorted(desks.items()))}) -> {HITS_FILE.name}")
    return HITS_FILE
