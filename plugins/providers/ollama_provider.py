"""Ollama as ModelProvider via its native API (no SDK needed). Env: OLLAMA_URL (default http://localhost:11434),
OLLAMA_MODEL (default gemma3:12b), OLLAMA_MEMO_MODEL (optional). Forces JSON output; retries once on bad JSON.
Norwegian quality depends heavily on the model — test with a NorwAI/NorMistral GGUF if you have the VRAM."""
from __future__ import annotations
import json, os
from typing import Any
import httpx
from core.registry import register
from core.schema import Context, Draft
from .anthropic_provider import MEMO_SYSTEM

URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("OLLAMA_MODEL", "gemma3:12b")


class OllamaProvider:
    name = "ollama"
    label = "Ollama"   # named in the AI marking

    def _json(self, system: str, user: str, model: str = MODEL) -> tuple[dict, dict[str, int]]:
        last = None
        for attempt in range(2):
            r = httpx.post(f"{URL}/api/chat", timeout=600, json={
                "model": model, "stream": False, "format": "json",
                "options": {"temperature": 0.2, "num_ctx": 32768},
                "messages": [{"role": "system", "content": system + ("\n\nYour previous answer was not valid JSON. Return only a JSON object." if attempt else "")},
                             {"role": "user", "content": user}]})
            r.raise_for_status()
            d = r.json()
            text = d["message"]["content"].strip().removeprefix("```json").removesuffix("```").strip()
            usage = {"input": d.get("prompt_eval_count", 0), "output": d.get("eval_count", 0)}
            try:
                return json.loads(text), usage
            except json.JSONDecodeError as e:
                last = e
        raise ValueError(f"ollama returned invalid JSON twice: {last}")

    def draft(self, template: str, ctx: Context, product: dict[str, Any], revise_from: dict | None = None) -> tuple[Draft, dict[str, int]]:
        system = template + "\n\nOutput a single JSON object: {\"headline\": str, \"body\": str, \"claims\": [{\"claim\": str, \"source_url\": str|null}], \"sections\": {}}"
        user: dict[str, Any] = {"context": {"primary": ctx.primary, "related": ctx.related, "beat": ctx.beat, "meta": ctx.meta}}
        if revise_from:
            user["revise"] = {"previous_draft": revise_from["draft"].__dict__, "ethics_memo": revise_from["memo"],
                              "style_check": revise_from["style"],
                              "instruction": "Resolve required_action items and style fixes without inventing facts. Same JSON."}
        d, u = self._json(system, json.dumps(user, ensure_ascii=False, default=str))
        return Draft(headline=d.get("headline", ""), body=d.get("body", ""), claims=d.get("claims", []), sections=d.get("sections", {})), u

    def memo(self, draft: Draft, screen: dict[str, Any], product: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
        return self._json(MEMO_SYSTEM, json.dumps({"draft": draft.__dict__, "screen": screen}, ensure_ascii=False),
                          model=os.environ.get("OLLAMA_MEMO_MODEL", MODEL))


register("provider", OllamaProvider())
