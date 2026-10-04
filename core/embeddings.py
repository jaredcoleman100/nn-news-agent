"""One embedding function for the whole system, chosen by EMBEDDER env: ollama | gemini | local.
Ingest, seed, related-item search and precedent must all use the same one; changing it means re-embedding.
    ollama: EMBED_MODEL default bge-m3 (1024-d, multilingual)   gemini: gemini-embedding (set EMBED_DIM)   local: gte-small (384-d)
"""
from __future__ import annotations
import os
import time
from functools import lru_cache

DEFAULT_MODEL = {"ollama": "bge-m3", "gemini": "gemini-embedding-001", "local": "Supabase/gte-small"}
DEFAULT_DIM = {"ollama": 1024, "gemini": 768, "local": 384}

EMBEDDER = os.environ.get("EMBEDDER", "ollama")
if EMBEDDER not in DEFAULT_MODEL:       # a typo here used to raise a bare KeyError at import
    raise ValueError(f"EMBEDDER={EMBEDDER!r} is not one of {sorted(DEFAULT_MODEL)}")
EMBED_MODEL = os.environ.get("EMBED_MODEL", DEFAULT_MODEL[EMBEDDER])
EMBED_DIM = int(os.environ.get("EMBED_DIM", DEFAULT_DIM[EMBEDDER]))


def embed(texts: list[str]) -> list[list[float]]:
    texts = [t[:8000] for t in texts]
    if EMBEDDER == "ollama":
        import httpx
        r = httpx.post(f"{os.environ.get('OLLAMA_URL', 'http://localhost:11434')}/api/embed", timeout=300,
                       json={"model": EMBED_MODEL, "input": texts})
        r.raise_for_status()
        return r.json()["embeddings"]
    if EMBEDDER == "gemini":
        return _gemini(texts)
    return _local()(texts)


# The SDK sends one batchEmbedContents request per call, but the free-tier quota
# (EmbedContentRequestsPerMinutePerUserPerProjectPerModel, limit 100) counts each *text*,
# not each request. A 64-item scoring batch therefore costs 64 units and two back-to-back
# batches exceed the minute allowance, which is how a 736-item backlog died with 429.
# Chunk, then wait it out: the quota refills per minute and the backlog is not urgent.
EMBED_CHUNK = int(os.environ.get("EMBED_CHUNK", "32"))
EMBED_RETRIES = int(os.environ.get("EMBED_RETRIES", "5"))
# The free tier allows ~100 texts per minute, counted per text and not per request.
# Sleeping len(chunk)*60/RPM *after* each request was not enough: it skipped the pause after
# a document's final chunk, so consecutive documents fired back to back, and it rode the
# limit with no headroom. All six US strategy PDFs still died on 429.
# A trailing-window limiter is the right shape for a per-minute quota: it holds across
# documents and across separate embed() calls in one process. Set EMBED_RPM very high on a
# paid key to make it a no-op.
EMBED_RPM = int(os.environ.get("EMBED_RPM", "90"))      # headroom under the 100/min ceiling
_sent: list[list[float]] = []                            # [[monotonic_ts, text_count], ...]


def _pace(n: int) -> None:
    """Block until sending n more texts keeps the trailing 60s under EMBED_RPM."""
    if EMBED_RPM <= 0:
        return
    while True:
        now = time.monotonic()
        while _sent and now - _sent[0][0] > 60.0:
            _sent.pop(0)
        used = int(sum(c for _, c in _sent))
        if used + n <= EMBED_RPM or not _sent:
            _sent.append([now, float(n)])
            return
        wait = 60.0 - (now - _sent[0][0]) + 0.5
        print(f"  embed: pacing {wait:.0f}s ({used} texts in trailing minute, need {n})")
        time.sleep(max(wait, 1.0))


class DailyQuotaExhausted(RuntimeError):
    """The per-DAY free-tier allowance is gone. Waiting will not help before it resets."""


def _throttled(e: Exception) -> bool:
    """Retry a per-minute limit; never retry a per-day one.

    The free tier enforces both: 100 texts/minute and 1000 texts/day
    (EmbedContentRequestsPerDayPerUserPerProjectPerModel-FreeTier). They return the same 429,
    so backing off blindly burns minutes per document against a cap that resets at midnight.
    Six US strategy PDFs each spent ~7 minutes retrying a daily cap before failing."""
    text = str(e)
    if "PerDay" in text:
        raise DailyQuotaExhausted(
            "Gemini free-tier embedding allowance for today is exhausted (1000 texts/day). "
            "Options: wait for the daily reset, move to a paid key (a few cents for this "
            "workload), or switch to EMBEDDER=ollama with bge-m3, which is unmetered and is "
            "also the multilingual fix for the ru/fi/de/sv sources.") from None
    return getattr(e, "code", None) in (429, 500, 502, 503, 504) or "RESOURCE_EXHAUSTED" in text         or "UNAVAILABLE" in text


def _gemini(texts: list[str]) -> list[list[float]]:
    from google import genai
    from google.genai import types
    c = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    cfg = types.EmbedContentConfig(output_dimensionality=EMBED_DIM)
    out: list[list[float]] = []
    for i in range(0, len(texts), EMBED_CHUNK):
        chunk = texts[i:i + EMBED_CHUNK]
        for attempt in range(EMBED_RETRIES):
            try:
                _pace(len(chunk))
                r = c.models.embed_content(model=EMBED_MODEL, contents=chunk, config=cfg)
                out += [e.values for e in r.embeddings]
                break
            except Exception as e:              # noqa: BLE001
                if not _throttled(e) or attempt == EMBED_RETRIES - 1:
                    raise
                wait = 20 * (attempt + 1)       # the quota is per minute; wait one out
                print(f"  embed: throttled, waiting {wait}s ({len(chunk)} texts)")
                time.sleep(wait)
    return out


@lru_cache(maxsize=1)
def _local():
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(EMBED_MODEL)
    return lambda ts: m.encode(ts, normalize_embeddings=True).tolist()
