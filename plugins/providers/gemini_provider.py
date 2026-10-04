"""Gemini as ModelProvider via the google-genai SDK (pip install google-genai). Env: GEMINI_API_KEY, GEMINI_MODEL.
Same contract as the Anthropic provider: templated draft, schema-bound memo, JSON only, no tools, no autonomy."""
from __future__ import annotations
import json, os, time
from typing import Any
from core.registry import register
from core.schema import Context, Draft
from .anthropic_provider import MEMO_SYSTEM

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")   # verify against ai.google.dev/models at deploy time
# Thinking tokens are charged against max_output_tokens on 2.5+ models: a 4000 budget left only ~400
# for the answer, truncating the JSON mid-string. Keep headroom for thoughts AND the draft.
MAX_OUTPUT_TOKENS = int(os.environ.get("GEMINI_MAX_OUTPUT_TOKENS", "16000"))
# The 3.x flash builds return 503 UNAVAILABLE often enough that one attempt makes a scheduled
# product (the 06:00 digest) unreliable. Try the configured model, then progressively older builds.
FALLBACK_MODELS = [m.strip() for m in os.environ.get(
    # 2.5-flash before 3.5-flash on purpose: 3.5 costs $1.50/$9.00 per 1M vs 3.6's $0.75/$3.75
    # and 2.5's $0.30/$2.50, so the cheapest usable build is tried before the priciest.
    "GEMINI_FALLBACK_MODELS", "gemini-2.5-flash,gemini-3.5-flash").split(",") if m.strip()]
ATTEMPTS_PER_MODEL = int(os.environ.get("GEMINI_ATTEMPTS_PER_MODEL", "2"))
RETRY_STATUS = (429, 500, 502, 503, 504)
# Ceiling on one "fast" call (translation). Unbounded is the dangerous default: the fast path runs
# inside the hourly ingest, where an SDK call that never returns hangs the whole pass.
FAST_TIMEOUT_MS = int(os.environ.get("GEMINI_FAST_TIMEOUT_MS", "150000"))


def _min_thinking(model: str):
    """Least thinking the model family allows.

    Translation is transposition, not reasoning, and thinking tokens are charged against
    max_output_tokens -- leaving the default budget on made a single 8000-character item take
    minutes. The knob is family-specific: 3.x takes `thinking_level`, 2.5 takes `thinking_budget`,
    and sending the wrong one is a 400, so choose by model name rather than sending both.
    """
    from google.genai import types
    if model.startswith("gemini-3"):
        return types.ThinkingConfig(thinking_level="low")
    return types.ThinkingConfig(thinking_budget=0)


class _Unparseable(ValueError):
    """Model returned non-JSON. Generation is stochastic, so a re-draw often fixes it."""


def _transient(e: Exception) -> bool:
    """Retry capacity and rate limits; never retry a bad request or a bad key."""
    if isinstance(e, _Unparseable):
        return True
    if getattr(e, "code", None) in RETRY_STATUS:
        return True
    return any(t in str(e).lower() for t in ("unavailable", "resource_exhausted", "internal",
                                            "deadline", "timed out", "timeout"))


class GeminiProvider:
    name = "gemini"
    label = "Gemini"   # named in the AI marking

    def __init__(self) -> None:
        self._c = None
        self.last_model: str | None = None

    def _client(self):
        if self._c is None:
            from google import genai
            self._c = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        return self._c

    def _json(self, system: str, user: str, max_output_tokens: int | None = None,
              fast: bool = False, model: str | None = None) -> tuple[dict, dict[str, int]]:
        """Configured model first, then the fallback chain; transient failures are retried.

        `fast` switches thinking off and bounds the HTTP call -- for mechanical work such as
        translation, where there is nothing to reason about and a hang is worse than a failure.
        """
        first = model or MODEL
        models = [first] + [m for m in ([MODEL] + FALLBACK_MODELS) if m != first]
        last: Exception | None = None
        for model in models:
            for attempt in range(ATTEMPTS_PER_MODEL):
                try:
                    out = self._call(model, system, user, max_output_tokens, fast)
                    self.last_model = model   # recorded in reports.versions for the audit trail
                    return out
                except Exception as e:
                    if not _transient(e):
                        raise
                    last = e
                    time.sleep(min(2 ** attempt, 8))
        raise RuntimeError(f"gemini: no usable response from {models}; last error: {last}")

    def _call(self, model: str, system: str, user: str, max_output_tokens: int | None = None,
              fast: bool = False) -> tuple[dict, dict[str, int]]:
        from google.genai import types
        cfg: dict[str, Any] = {"system_instruction": system, "response_mime_type": "application/json",
                               "max_output_tokens": max_output_tokens or MAX_OUTPUT_TOKENS,
                               "temperature": 0.3}
        if fast:
            cfg["thinking_config"] = _min_thinking(model)
            cfg["http_options"] = types.HttpOptions(timeout=FAST_TIMEOUT_MS)
        r = self._client().models.generate_content(
            model=model, contents=user, config=types.GenerateContentConfig(**cfg))
        text = (r.text or "").strip().removeprefix("```json").removesuffix("```").strip()
        um = getattr(r, "usage_metadata", None)
        usage = {"input": getattr(um, "prompt_token_count", 0) or 0, "output": getattr(um, "candidates_token_count", 0) or 0}
        try:
            return json.loads(text), usage
        except json.JSONDecodeError as e:
            fr = r.candidates[0].finish_reason if getattr(r, "candidates", None) else None
            raise _Unparseable(f"{model} returned unparseable JSON ({e}). finish_reason={fr} "
                             f"thoughts={getattr(um, 'thoughts_token_count', None)} output={usage['output']} "
                             f"max_output_tokens={MAX_OUTPUT_TOKENS} - raise GEMINI_MAX_OUTPUT_TOKENS if truncated") from None

    def draft(self, template: str, ctx: Context, product: dict[str, Any], revise_from: dict | None = None) -> tuple[Draft, dict[str, int]]:
        system = template + "\n\nOutput JSON only: {\"headline\": str, \"body\": str, \"claims\": [{\"claim\": str, \"source_url\": str|null}], \"sections\": {}}"
        user: dict[str, Any] = {"context": {"primary": ctx.primary, "related": ctx.related, "beat": ctx.beat, "meta": ctx.meta}}
        if revise_from:
            user["revise"] = {"previous_draft": revise_from["draft"].__dict__, "ethics_memo": revise_from["memo"],
                              "style_check": revise_from["style"],
                              "instruction": "Resolve required_action items and style fixes without inventing facts. Same JSON."}
        d, u = self._json(system, json.dumps(user, ensure_ascii=False, default=str))
        return Draft(headline=d.get("headline", ""), body=d.get("body", ""), claims=d.get("claims", []), sections=d.get("sections", {})), u

    def memo(self, draft: Draft, screen: dict[str, Any], product: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
        return self._json(MEMO_SYSTEM, json.dumps({"draft": draft.__dict__, "screen": screen}, ensure_ascii=False))


register("provider", GeminiProvider())
