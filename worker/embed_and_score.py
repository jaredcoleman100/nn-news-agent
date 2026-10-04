"""Worker-side embedding + scoring. Run as a loop or cron next to Ollama. The Edge Function only fetches raw items;
this fills `embedding` and writes `hits`. Replaces the embed/score part of supabase/functions/ingest when EMBEDDER != local.
    PYTHONPATH=. python worker/embed_and_score.py
"""
from __future__ import annotations
import os
from core.embeddings import embed
from plugins.loaders.db import sb

BATCH = 32


def run_once() -> dict:
    rows = sb().table("items").select("id,title,body").is_("embedding", "null").order("fetched_at").limit(BATCH).execute().data
    if not rows:
        return {"embedded": 0, "hits": 0}
    vecs = embed([f"{r['title'] or ''}\n{(r['body'] or '')[:2000]}" for r in rows])
    newsroom = os.environ.get("NEWSROOM_ID", "nord-norge")   # beats table is shared
    beats = {b["id"]: b["threshold"] for b in sb().table("beats").select("id,threshold")
             .eq("active", True).eq("newsroom_id", newsroom).execute().data}
    cap = int(sb().table("config").select("value").eq("key", "max_beats_per_item").single().execute().data["value"])
    hits = 0
    for r, v in zip(rows, vecs):
        sb().table("items").update({"embedding": v}).eq("id", r["id"]).execute()
        over = [m for m in sb().rpc("match_beats", {"query_embedding": v, "newsroom": newsroom}).execute().data
                if m["score"] >= beats.get(m["beat_id"], 1.0)]
        # See run.py score(): cap the beats per item so one story is one memo.
        for m in sorted(over, key=lambda x: x["score"], reverse=True)[:cap]:
            sb().table("hits").upsert({"item_id": r["id"], "beat_id": m["beat_id"], "score": m["score"]},
                                      on_conflict="item_id,beat_id", ignore_duplicates=True).execute()
            hits += 1
    return {"embedded": len(rows), "hits": hits}


if __name__ == "__main__":
    import time
    loop = os.environ.get("LOOP", "0") == "1"
    while True:
        print(run_once())
        if not loop:
            break
        time.sleep(120)
