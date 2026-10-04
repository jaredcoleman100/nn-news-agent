"""Background reference corpus: ingest a document with provenance, and retrieve chunks.

This is the third role in the system, distinct from the two that already existed:

    items      -> hits -> drafted news reports          (fresh news, per source)
    document   -> one story                              (a new public document, document-story)
    reference  -> retrieved as context while drafting    (this module)

A strategy PDF is not news. Put the 2024 DoD Arctic Strategy in `items` and the beat scorer
will match it at ~0.7 against arctic-security and draft a news report about a two-year-old
document. So reference material lives in its own tables and is never scored against beats.

Provenance is the point. `reference/README.md` records what goes wrong without it: a
synthesised analysis with unattributed figures was used to derive beats.json, and nothing in
the ethics layer catches it, because the `single_source_or_social_media` screen inspects the
draft's sources and an internal corpus looks authoritative. So every document carries a
publisher, a date, a tier and a `verified` flag, and retrieval always returns them.

    ingest(url, title, publisher, tier, doc_date=None)   fetch, chunk, embed, store
    search(query, k=6)                                   retrieve with provenance
"""
from __future__ import annotations

import hashlib
import io as _io
import os
import re
from datetime import date
from typing import Any

import httpx

from core.embeddings import embed
from plugins.loaders.db import sb

UA = {"User-Agent": "nn-news-agent/0.2 (newsroom reference corpus; contact your editor)"}
CHUNK_CHARS = 1200
CHUNK_OVERLAP = 150
_WS = re.compile(r"\s+")
TIERS = ("primary", "secondary", "unverified")

# A soft error page returns HTTP 200, so raise_for_status() passes and the corpus silently
# acquires an authoritative-looking document that is actually an apology. state.gov served
# "We're sorry, this site is currently experiencing technical difficulties ... Exception:
# forbidden" (128 chars) and it was stored as a primary-tier State Department strategy.
MIN_DOC_CHARS = int(os.environ.get("REFERENCE_MIN_CHARS", "2000"))
ERROR_SIGNS = (
    "experiencing technical difficulties", "exception: forbidden", "access denied",
    "page not found", "404 not found", "403 forbidden", "are you a robot",
    "enable javascript", "request blocked", "service unavailable",
)


def _text_from_pdf(raw: bytes) -> str:
    import pdfplumber
    with pdfplumber.open(_io.BytesIO(raw)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def _text_from_html(html: str) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "nav", "aside", "header", "footer", "form"]):
        t.decompose()
    node = soup.find("main") or soup.find("article") or soup.body or soup
    return node.get_text("\n", strip=True)


def fetch_text(url: str) -> tuple[str, str]:
    """Returns (text, sha256 of the raw bytes). The hash detects silent revisions later."""
    r = httpx.get(url, headers=UA, timeout=90, follow_redirects=True)
    r.raise_for_status()
    digest = hashlib.sha256(r.content).hexdigest()
    ctype = (r.headers.get("content-type") or "").lower()
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        return _text_from_pdf(r.content), digest
    return _text_from_html(r.text), digest


def chunk(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Paragraph-aware chunks with a little overlap, so a sentence split across a boundary is
    still retrievable from one side of it."""
    text = _WS.sub(" ", text).strip()
    if not text:
        return []
    out, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):                       # prefer a sentence boundary
            window = text.rfind(". ", start + size // 2, end)
            if window > 0:
                end = window + 1
        piece = text[start:end].strip()
        if piece:
            out.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return out


def ingest(url: str, title: str, publisher: str, tier: str,
           doc_date: str | date | None = None, license_note: str | None = None,
           verified: bool = False, newsroom_id: str = "nord-norge") -> dict[str, Any]:
    """Fetch, chunk, embed and store one reference document. Idempotent on url."""
    if tier not in TIERS:
        raise ValueError(f"tier must be one of {TIERS}, got {tier!r}")
    text, digest = fetch_text(url)
    low = text[:4000].lower()
    hit = next((sign for sign in ERROR_SIGNS if sign in low), None)
    if hit:
        raise ValueError(f"error page at {url} (matched {hit!r}); nothing stored")
    if len(text) < MIN_DOC_CHARS:
        raise ValueError(f"only {len(text)} chars at {url}, below REFERENCE_MIN_CHARS "
                         f"({MIN_DOC_CHARS}); a strategy document is not this short")
    pieces = chunk(text)
    if not pieces:
        raise ValueError(f"no extractable text at {url}")

    # Embed first. Writing the doc row before the failure-prone step left phantom documents:
    # a reference_docs row with zero chunks, which looks ingested and can never be retrieved.
    vecs = embed(pieces)

    row = sb().table("reference_docs").upsert({
        "newsroom_id": newsroom_id, "title": title, "publisher": publisher, "url": url,
        "doc_date": str(doc_date) if doc_date else None, "tier": tier,
        "verified": verified, "license_note": license_note, "sha256": digest,
    }, on_conflict="url").execute().data[0]
    doc_id = row["id"]
    sb().table("reference_chunks").delete().eq("doc_id", doc_id).execute()
    for i in range(0, len(pieces), 50):
        sb().table("reference_chunks").insert(
            [{"doc_id": doc_id, "ord": i + j, "text": p, "embedding": v}
             for j, (p, v) in enumerate(zip(pieces[i:i + 50], vecs[i:i + 50]))]).execute()
    return {"doc_id": doc_id, "chunks": len(pieces), "chars": len(text), "sha256": digest[:12]}


def search(query: str, k: int = 6, min_score: float = 0.0) -> list[dict[str, Any]]:
    """Retrieve chunks with provenance attached. Never returns text without its source."""
    v = embed([query])[0]
    rows = sb().rpc("match_reference", {"query_embedding": v, "k": k}).execute().data or []
    return [r for r in rows if (r.get("score") or 0) >= min_score]


def as_context(query: str, k: int = 6) -> list[dict[str, Any]]:
    """Shape for a Context/meta payload: the drafter must see the tier and verified flag so an
    unverified figure cannot be presented as established fact."""
    return [{
        "text": r["text"],
        "source": f'{r["publisher"]}, "{r["title"]}"' + (f' ({r["doc_date"]})' if r.get("doc_date") else ""),
        "url": r["url"],
        "tier": r["tier"],
        "verified": bool(r.get("verified")),
        "score": round(float(r.get("score") or 0), 3),
    } for r in search(query, k=k)]
