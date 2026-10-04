"""Seed beats (embedded with core.embeddings — same EMBEDDER as ingest; vector column width must equal EMBED_DIM) and starter sources into Supabase. Embeds beats with the same gte-small model
the ingest function uses (via the ingest function's /embed sibling, or locally with sentence-transformers).
    python worker/seed.py
"""
import json, os
from pathlib import Path
from supabase import create_client
from core.embeddings import embed, EMBED_DIM

SB = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
beats = json.loads((Path(__file__).parents[1] / "config" / "nord-norge" / "beats.json").read_text(encoding="utf-8"))["beats"]

for b in beats:
    text = b["description"] + " " + " ".join(b["keywords_nb"] + b["keywords_en"])
    emb = embed([text])[0]
    SB.table("beats").upsert({"id": b["id"], "name": b["name"], "description": b["description"],
                              "keywords": b["keywords_nb"] + b["keywords_en"],
                              "ethics_profile": b["ethics_profile"], "embedding": emb}).execute()
print(f"seeded {len(beats)} beats")

SOURCES = [
    ("NRK Nordland", "rss", "https://www.nrk.no/nordland/toppsaker.rss", None),
    ("NRK Troms og Finnmark", "rss", "https://www.nrk.no/tromsogfinnmark/toppsaker.rss", None),
    ("NRK Sápmi", "rss", "https://www.nrk.no/sapmi/toppsaker.rss", "reconciliation-minorities"),
    ("Svalbardposten", "rss", "https://www.svalbardposten.no/rss", "svalbard-climate"),
    ("Fiskeribladet", "rss", "https://www.fiskeribladet.no/rss", "fisheries"),
    ("Forsvaret", "rss", "https://www.forsvaret.no/aktuelt-og-presse/rss", "arctic-security"),
    ("Sametinget", "rss", "https://sametinget.no/rss", "reconciliation-minorities"),
]
for name, kind, url, hint in SOURCES:
    SB.table("sources").upsert({"name": name, "kind": kind, "url": url, "beat_hint": hint}, on_conflict="url").execute()
print("seeded sources — verify each RSS URL resolves; several are best guesses")
