"""GPT-5 as ModelProvider. Drafting is templated; the memo is schema-bound. No tool use, no autonomy.

WHY THIS EXISTS
The desk ran entirely on Gemini, and Gemini's prepaid credits run dry most days -- drafting and
translation both stop, the site freezes, and the English column empties, with nothing saying so.
A second provider is the fix for that, not a preference about model quality.

Chosen 2026-09-30 after checking what credentials this machine actually holds: ANTHROPIC_API_KEY is
present in .env but empty, OPENAI_API_KEY is populated and works.

INTERFACE
Matches plugins/providers/gemini_provider.py: `_json(system, user, max_output_tokens=, fast=,
model=)` plus `draft()` and `memo()`. core/translate.py calls `_json` with those keyword arguments
and falls back to the two-argument form on TypeError, so keeping the signature means translation
can be pointed here with an environment variable and nothing else.
"""
from __future__ import annotations
import json, os, re
from typing import Any
import openai
from core.registry import register
from core.schema import Context, Draft

# gpt-5 rather than gpt-5-mini: drafting is the whole point of routing here, and the satire desk is
# the hardest writing task on this engine. Override per product with the `model` argument, or
# globally with OPENAI_MODEL.
MODEL = os.environ.get("OPENAI_MODEL", "gpt-5")

# The model used when the caller asks for `fast` -- translation, which is bulk, high-volume and has
# nothing to reason about. Keeping it separate means a translation backlog cannot spend drafting
# money, and the two can be tuned independently.
FAST_MODEL = os.environ.get("OPENAI_FAST_MODEL", "gpt-5-mini")

# A satire draft is 500-850 words of Bokmål plus the same again in English plus five `sections`, all
# inside one JSON object, and _json() ends in json.loads() -- a response cut off at the output limit
# does not degrade, it raises JSONDecodeError and loses the run.
MAX_TOKENS = int(os.environ.get("OPENAI_MAX_TOKENS", "16000"))

MEMO_SYSTEM = """You are the ethics desk. You receive a draft and the deterministic ethics screen (flags, clauses,
memo_schema). Write the memo strictly in memo_schema as JSON and nothing else. Cite the clause id for every flag and
quote the exact trigger sentence. Name the closest prior ruling in the screen's related_units if any and say how this
case differs. You may not set publication_gate lower than the screen returned."""


# Postgres text columns cannot hold a NUL, and json.loads happily produces one from a literal
# U+0000 in the model's reply -- which gpt-5 emitted on the first short-letter draft. The insert
# then fails with "unsupported Unicode escape sequence", after the generation has been paid for.
# Strip the control characters that cannot survive the round trip, keeping tab/newline/return.
_CTRL = {c: None for c in range(0x20) if c not in (0x09, 0x0A, 0x0D)}
_CTRL[0x7F] = None


def _clean(value):
    """Recursively drop characters Postgres will refuse."""
    if isinstance(value, str):
        return value.translate(_CTRL)
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    return value


# gpt-5 occasionally emits a translation in which escape sequences have collapsed into their hex
# digits: «Norway27s» for "Norway's", «Se1pmi» for "Sapmi". Seen once, on the English half of a
# letter whose Norwegian half was clean, and it reached the published page before anyone noticed.
#
# This detects it and raises. It does NOT try to repair: "27" could be an apostrophe or it could be
# a number, and a repair pass that guesses wrong corrupts text silently, which is worse than a
# failed run that can simply be retried.
_ARTIFACT = re.compile(r"[A-Za-z](?:27|e1|e5|e6|f8|f6|fc|c3)[a-z]")


def _assert_no_escape_artifacts(data, model: str) -> None:
    for key in ("body", "headline"):
        if _ARTIFACT.search(str(data.get(key) or "")):
            raise RuntimeError(f"{model}: escape sequences collapsed to hex in `{key}`")
    for key, value in (data.get("sections") or {}).items():
        if _ARTIFACT.search(str(value or "")):
            raise RuntimeError(f"{model}: escape sequences collapsed to hex in `sections.{key}`")


class OpenAIProvider:
    name = "openai"
    label = "GPT-5"   # named in the AI marking the templates emit

    def __init__(self) -> None:
        self._c = None

    def _client(self):
        if self._c is None:
            self._c = openai.OpenAI()
        return self._c

    def _json(self, system: str, user: str, max_output_tokens: int | None = None,
              fast: bool = False, model: str | None = None) -> tuple[dict, dict[str, int]]:
        """One JSON reply. `fast` picks the cheap model for bulk work (translation)."""
        use = model or (FAST_MODEL if fast else MODEL)
        # response_format json_object rather than parsing fenced text: every caller here ends in
        # json.loads(), and a model that wraps its reply in ```json is the single most common way
        # that fails. This makes the server guarantee parseable JSON instead.
        r = self._client().chat.completions.create(
            model=use,
            max_completion_tokens=max_output_tokens or MAX_TOKENS,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        choice = r.choices[0]
        if choice.finish_reason == "length":
            raise RuntimeError(
                f"{use} hit the output cap ({max_output_tokens or MAX_TOKENS}); the JSON is "
                f"truncated. Raise OPENAI_MAX_TOKENS rather than letting json.loads fail on a "
                f"cut-off object.")
        text = (choice.message.content or "").strip()
        if not text:
            raise RuntimeError(f"{use} returned no content (finish_reason={choice.finish_reason})")
        usage = {"input": getattr(r.usage, "prompt_tokens", 0) or 0,
                 "output": getattr(r.usage, "completion_tokens", 0) or 0}
        data = _clean(json.loads(text))
        _assert_no_escape_artifacts(data, use)
        return data, usage

    def draft(self, template: str, ctx: Context, product: dict[str, Any],
              revise_from: dict | None = None) -> tuple[Draft, dict[str, int]]:
        system = template + ("\n\nOutput JSON only: {\"headline\": str, \"body\": str, "
                             "\"claims\": [{\"claim\": str, \"source_url\": str|null}], "
                             "\"sections\": {}}")
        user: dict[str, Any] = {"context": {"primary": ctx.primary, "related": ctx.related,
                                            "beat": ctx.beat, "meta": ctx.meta}}
        if revise_from:
            user["revise"] = {
                "previous_draft": revise_from["draft"].__dict__,
                "ethics_memo": revise_from["memo"],
                "style_check": revise_from["style"],
                "instruction": "Resolve required_action items and style fixes without inventing "
                               "facts. Same JSON.",
            }
        d, u = self._json(system, json.dumps(user, ensure_ascii=False, default=str),
                          model=(product.get("model") or None))
        return Draft(headline=d.get("headline", ""), body=d.get("body", ""),
                     claims=d.get("claims", []), sections=d.get("sections", {})), u

    def memo(self, draft: Draft, screen: dict[str, Any],
             product: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
        return self._json(MEMO_SYSTEM,
                          json.dumps({"draft": draft.__dict__, "screen": screen},
                                     ensure_ascii=False))


register("provider", OpenAIProvider())
