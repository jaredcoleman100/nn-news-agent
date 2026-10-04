"""Claude as ModelProvider. Drafting is templated; the memo is schema-bound. No tool use, no autonomy."""
from __future__ import annotations
import json, os
from typing import Any
import anthropic
from core.registry import register
from core.schema import Context, Draft

# Opus by default: the satire desk is the hardest writing task on this engine, and drafting quality
# is the whole point of routing to Claude at all. Override with MODEL for a cheaper desk.
MODEL = os.environ.get("MODEL", "claude-opus-5")

# 3000 was too low and was a truncation bug waiting to happen, not a cost saving. A satire draft is
# 500-850 words of Bokmål plus the same again in English plus five `sections`, all inside one JSON
# object -- and _json() ends in json.loads(), so a response cut off at max_tokens does not degrade,
# it raises JSONDecodeError and loses the run. Anthropic's own guidance is ~16000 for non-streaming
# requests, which stays inside the SDK's HTTP timeout.
MAX_TOKENS = int(os.environ.get("ANTHROPIC_MAX_TOKENS", "16000"))

MEMO_SYSTEM = """You are the ethics desk. You receive a draft and the deterministic ethics screen (flags, clauses,
memo_schema). Write the memo strictly in memo_schema as JSON and nothing else. Cite the clause id for every flag and
quote the exact trigger sentence. Name the closest prior ruling in the screen's related_units if any and say how this
case differs. You may not set publication_gate lower than the screen returned."""


class AnthropicProvider:
    name = "anthropic"
    label = "Claude"   # named in the AI marking

    def __init__(self) -> None:
        self._c = None

    def _client(self):
        if self._c is None:
            self._c = anthropic.Anthropic()
        return self._c

    def _json(self, system: str, user: str) -> tuple[dict, dict[str, int]]:
        # `thinking` is deliberately not passed. Omitting it runs adaptive thinking on the models
        # this desk uses (Opus 5, Sonnet 5) while staying valid on older ones; passing
        # {"type": "adaptive"} explicitly would 400 on Haiku, which still takes budget_tokens.
        r = self._client().messages.create(model=MODEL, max_tokens=MAX_TOKENS, system=system,
                                           messages=[{"role": "user", "content": user}])
        text = "".join(b.text for b in r.content if b.type == "text").strip()
        text = text.removeprefix("```json").removesuffix("```").strip()
        if r.stop_reason == "max_tokens":
            raise RuntimeError(
                f"{MODEL} hit max_tokens ({MAX_TOKENS}); the JSON is truncated. Raise "
                f"ANTHROPIC_MAX_TOKENS rather than letting json.loads fail on a cut-off object.")
        return json.loads(text), {"input": r.usage.input_tokens, "output": r.usage.output_tokens}

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


register("provider", AnthropicProvider())
