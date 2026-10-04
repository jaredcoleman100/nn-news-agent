"""Deterministic provider for tests and dry runs. Echoes context into a draft; memo mirrors the screen."""
from __future__ import annotations
from typing import Any
from core.registry import register
from core.schema import Context, Draft


class FakeProvider:
    name = "fake"
    label = "test"   # named in the AI marking

    def draft(self, template: str, ctx: Context, product: dict[str, Any], revise_from=None) -> tuple[Draft, dict[str, int]]:
        p = ctx.primary[0] if ctx.primary else {}
        body = (p.get("body") or p.get("text") or "")[:600]
        if revise_from:
            body = body.replace("17 år", "ung").replace("Facebook", "en kilde")
        body += "\n\nDette utkastet er laget ved hjelp av kunstig intelligens (test) og er kontrollert av redaksjonen før publisering."
        return Draft(headline=p.get("title", "Utkast"), body=body, claims=[{"claim": "(fake)", "source_url": p.get("url")}]), {"input": 0, "output": 0}

    def memo(self, draft: Draft, screen: dict[str, Any], product: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
        return {"publication_gate": screen["publication_gate"],
                "flags": [{**{k: f[k] for k in ("flag", "severity", "clauses")}, "trigger": ", ".join(f["evidence"]), "assessment": f["why"], "required_action": "editor"} for f in screen["flags"]],
                "editor_decision_required": [f["flag"] for f in screen["flags"] if f["severity"] != "note"]}, {"input": 0, "output": 0}


register("provider", FakeProvider())
