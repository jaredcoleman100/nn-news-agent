"""Parallel English for archived items.

Every item keeps its source text verbatim and gains an English twin: `title_en`, `body_en`, and
the detected `lang`. Nothing is replaced -- the Norwegian (or Russian, Finnish, German, Swedish,
Northern Sami) original stays canonical, because it is what the beats are embedded against and
what the ethics screens read. English is additive, for the reader of the archive index.

    TRANSLATE=0                 switch it off entirely
    TRANSLATE_PROVIDER=gemini   which registered provider does the work
    TRANSLATE_BODY_CHARS=8000   per-item body cap (matches enrich's own cap, so nothing extra
                                is lost; lower it to trade fidelity for cost)
    TRANSLATE_BATCH_CHARS=12000 input characters per model call

Cost, measured against the live table (1074 items, 1.68M chars): a full backfill is about $1.20
on gemini-2.5-flash, and a normal day of ~350 items about $0.38. That is the reason batching is
budgeted by characters rather than by item count -- see `batches()`.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Iterator

from core import registry

ENABLED = os.environ.get("TRANSLATE", "1") != "0"
PROVIDER = os.environ.get("TRANSLATE_PROVIDER", "gemini")
BODY_CHARS = int(os.environ.get("TRANSLATE_BODY_CHARS", "8000"))
# 2500, measured rather than guessed. Against gemini-3.6-flash on 2026-09-15: ~300 chars and
# ~2000 chars both returned in ~3.8s, while ~8000 chars did not return inside 40s at all. Latency
# is driven by the output the call has to generate, not by capacity alone, so many small calls
# beat few large ones -- and a small call that fails costs seconds to retry instead of minutes.
BATCH_CHARS = int(os.environ.get("TRANSLATE_BATCH_CHARS", "2500"))
MAX_OUT = int(os.environ.get("TRANSLATE_MAX_OUTPUT_TOKENS", "8000"))
# Empty = use whatever GEMINI_MODEL the provider is configured with, currently gemini-3.6-flash.
# This was briefly pinned to 2.5-flash on the theory that its true thinking_budget=0 would beat
# Gemini 3's thinking_level="low" floor. Measured head to head, that was wrong on both counts:
# 3.6 answered in 1.9s against 2.5's 23.5s, and 2.5 rendered «Hoyre» as "The right" -- translating
# a party name, which the prompt forbids -- where 3.6 kept it. The slowness that prompted the pin
# was a provider-wide 503 spike, not thinking. Set TRANSLATE_MODEL to override.
MODEL = os.environ.get("TRANSLATE_MODEL", "") or None
# Give up the whole pass after this many batches fail back to back. When Gemini is congested every
# model in the chain 503s, and one batch then costs ~260s of retries to achieve nothing: a 60-item
# pass would spend 40+ minutes failing, inside an hourly job. Two consecutive failures is enough to
# tell "the provider is down" from "this one batch was unlucky"; the items keep title_en null and
# the next pass picks them up.
MAX_CONSECUTIVE_FAILURES = int(os.environ.get("TRANSLATE_MAX_FAILURES", "2"))
# Seconds between calls. The Gemini free tier limits requests per MINUTE, and firing batches
# back to back blows through it in seconds: the run then gets 429 RESOURCE_EXHAUSTED, which the
# chain retries against every model and some of which comes back as 503, so the symptom looks
# like a provider outage rather than self-inflicted rate limiting. 6s = 10 requests/min. Set to 0
# on a billed key.
MIN_INTERVAL_S = float(os.environ.get("TRANSLATE_MIN_INTERVAL_S", "6"))

SYSTEM = """You translate Nordic and European news items into English for a newsroom archive.

For each numbered item you receive, return a faithful English rendering of its title and body.

Rules
- Translate, do not summarise, editorialise or expand. Same facts, same order, same emphasis.
- Keep proper nouns, place names, party names and institution names in their original form.
  Where a Sami/Norwegian dual form appears (Deatnu/Tana, Guovdageaidnu/Kautokeino), keep both
  exactly as written. Do not anglicise a place that has no established English name.
- Keep direct quotations as quotations. Translate them; do not paraphrase them into reported
  speech, and do not invent quotation marks that were not there.
- Norwegian compounds that name a specific scheme, body or law keep the original in parentheses
  after the English on first use, e.g. "the municipal revenue system (kommunenes inntektssystem)".
- If the body is empty, return an empty string for body_en. Never fabricate a body from a title.
- `lang` is the language you detected in the SOURCE text, as a short code: nb, nn, se, ru, fi,
  en, de, sv. Use nb for Norwegian Bokmal and nn for Nynorsk; do not guess from the source name.
- An item already in English is still returned, with lang "en" and the text unchanged.

Output JSON only: {"items": [{"i": <the integer i you were given>, "lang": str,
"title_en": str, "body_en": str}]}
Return exactly one object per input item, and echo `i` back unchanged -- results are matched on
it, and an item whose `i` is missing or unrecognised is discarded rather than misaligned."""


SYSTEM_TITLES = """You translate Nordic and European news headlines into English for a newsroom archive.

For each numbered item you receive, return a faithful English rendering of its headline.

Rules
- Translate, do not summarise or editorialise. A headline stays a headline.
- Keep proper nouns, place names, party names and institution names in their original form. Where a
  Sami/Norwegian dual form appears (Deatnu/Tana, Guovdageaidnu/Kautokeino), keep both exactly.
- A headline that is a quotation stays a quotation.
- `lang` is the language you detected in the SOURCE headline: nb, nn, se, ru, fi, en, de, sv. Use
  nb for Bokmal and nn for Nynorsk; do not guess from the source name.
- A headline already in English is returned unchanged, with lang "en".

Output JSON only: {"items": [{"i": <the integer i you were given>, "lang": str, "title_en": str}]}
Return exactly one object per input item and echo `i` back unchanged -- results are matched on it,
and an item whose `i` is missing or unrecognised is discarded rather than misaligned."""


SYSTEM_TITLES_NB = """Du oversetter nyhetsoverskrifter til norsk bokmål for et redaksjonsarkiv.

For hvert nummererte element returnerer du en trofast gjengivelse av overskriften på bokmål.

Regler
- Oversett, ikke sammenfatt eller kommenter. En overskrift forblir en overskrift.
- Behold egennavn, stedsnavn, partinavn og institusjonsnavn i sin opprinnelige form. Der et
  samisk/norsk dobbeltnavn forekommer (Deatnu/Tana, Guovdageaidnu/Kautokeino), behold begge.
- Kinesiske, japanske, arabiske, hindi- og persiske navn translittereres til latinsk skrift slik
  de vanligvis skrives på norsk. Behold originalen i parentes første gang for institusjoner og
  ordninger som ikke har et etablert norsk navn.
- En overskrift som er et sitat, forblir et sitat.
- Er kilden allerede på bokmål, returneres overskriften uendret.

Kun JSON: {"items": [{"i": <heltallet i du fikk>, "title_nb": str}]}
Returner nøyaktig ett objekt per element og gjenta `i` uendret — resultatene kobles på den, og et
element med manglende eller ukjent `i` forkastes framfor å bli feilkoblet."""


def _clip(text: str, limit: int) -> str:
    """Cut on a sentence or word boundary so the model is never handed a severed word."""
    s = (text or "").strip()
    if len(s) <= limit:
        return s
    cut = s[:limit]
    for sep in (". ", "! ", "? ", "\n", " "):
        at = cut.rfind(sep)
        if at > limit * 0.6:
            return cut[:at + len(sep.strip())].strip()
    return cut.strip()


def batches(rows: list[dict[str, Any]], titles_only: bool = False) -> Iterator[list[dict[str, Any]]]:
    """Group rows into model calls by input size, not by count.

    Item bodies run from a headline to enrich's 8000-char cap, a 16x spread. A fixed batch of N
    is therefore either wasteful on short items or, on a run of long ones, large enough that the
    JSON reply is truncated mid-string against the provider's max_output_tokens -- which the
    Gemini provider can only report as unparseable JSON. Budget the input instead, and let an
    oversized single item travel alone.
    """
    batch: list[dict[str, Any]] = []
    size = 0
    for r in rows:
        n = len(str(r.get("title") or ""))
        if not titles_only:
            n += len(_clip(str(r.get("body") or ""), BODY_CHARS))
        if batch and size + n > BATCH_CHARS:
            yield batch
            batch, size = [], 0
        batch.append(r)
        size += n
    if batch:
        yield batch


def _call(rows: list[dict[str, Any]], titles_only: bool = False,
          target: str = "en") -> tuple[dict[int, dict[str, str]], dict[str, int]]:
    # `_json` is not on the ModelProvider protocol, but both providers expose the same
    # (system, user) -> (dict, usage) shape, and the Gemini one carries the 503 fallback chain a
    # scheduled job needs. Going through the registry keeps the provider swappable.
    prov = registry.get("provider", PROVIDER)
    if titles_only:
        payload = {"items": [{"i": i, "title": str(r.get("title") or "")}
                             for i, r in enumerate(rows)]}
    else:
        payload = {"items": [{"i": i,
                              "title": str(r.get("title") or ""),
                              "body": _clip(str(r.get("body") or ""), BODY_CHARS)}
                             for i, r in enumerate(rows)]}
    user = json.dumps(payload, ensure_ascii=False)
    # Size the output ceiling to the input: a translation is close to 1:1 in tokens, plus JSON
    # overhead. Sending the provider's drafting default (16000) instead invites the model to spend
    # the headroom on thinking it does not need here.
    cap = min(MAX_OUT, len(user) // 2 + 1500)
    # Norwegian is titles-only for now: the nb backfill exists so the site's Norwegian column is
    # not empty on a Chinese or Arabic story, and a headline is what the card shows. Bodies follow
    # the same route when there is quota to spare.
    if target == "nb":
        system = SYSTEM_TITLES_NB
    else:
        system = SYSTEM_TITLES if titles_only else SYSTEM
    try:
        # fast=True: thinking off and the HTTP call bounded. Translation has nothing to reason
        # about, and this runs inside the hourly ingest where a hang costs the whole pass.
        data, usage = prov._json(system, user,
                                 max_output_tokens=cap, fast=True, model=MODEL)
    except TypeError:
        data, usage = prov._json(system, user)
    out: dict[int, dict[str, str]] = {}
    for got in data.get("items") or []:
        try:
            i = int(got.get("i"))
        except (TypeError, ValueError):
            continue                      # no index to match on; discarding beats misaligning
        if 0 <= i < len(rows):
            if target == "nb":
                # No `lang` here: the nb pass only ever runs on items whose language was already
                # detected by the English pass, and letting a second detection overwrite it would
                # let the two disagree about the same row.
                out[i] = {"title_nb": str(got.get("title_nb") or "").strip()}
                continue
            row = {"lang": str(got.get("lang") or "").strip()[:8] or "und",
                   "title_en": str(got.get("title_en") or "").strip()}
            if not titles_only:
                row["body_en"] = str(got.get("body_en") or "").strip()
            out[i] = row
    return out, usage


def translate(rows: list[dict[str, Any]], titles_only: bool = False,
              target: str = "en") -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Translate rows in place-safe fashion: returns [{id, lang, title_en, body_en}, ...].

    A failed batch is reported and skipped, never raised: the items keep `title_en is null` and
    are simply picked up by the next pass. Translation must not be able to stop ingest, because
    scoring and the beats depend on the source text, which is already stored.
    """
    if not ENABLED or not rows:
        return [], {"input": 0, "output": 0}
    done: list[dict[str, Any]] = []
    total = {"input": 0, "output": 0}
    failures = 0
    last_call = 0.0
    for batch in batches(rows, titles_only):
        wait = MIN_INTERVAL_S - (time.monotonic() - last_call)
        if last_call and wait > 0:
            time.sleep(wait)
        last_call = time.monotonic()
        try:
            got, usage = _call(batch, titles_only, target)
        except Exception as ex:  # noqa: BLE001
            failures += 1
            print(f"  translate: batch of {len(batch)} failed: {ex}", flush=True)
            if failures >= MAX_CONSECUTIVE_FAILURES:
                print(f"  translate: {failures} batches failed in a row, abandoning this pass "
                      f"({len(done)} translated before giving up)", flush=True)
                break
            continue
        failures = 0
        total["input"] += usage.get("input", 0)
        total["output"] += usage.get("output", 0)
        key = "title_nb" if target == "nb" else "title_en"
        for i, r in enumerate(batch):
            t = got.get(i)
            if not t or not t.get(key):
                continue                  # a title that came back empty is a failure, not a result
            done.append({"id": r["id"], **t})
    return done, total
