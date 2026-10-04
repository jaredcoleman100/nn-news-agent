from __future__ import annotations
import json
from typing import Any
from core.registry import register
from core.schema import Report

EMOJI = {"blocked": ":no_entry:", "review": ":warning:", "clear": ":white_check_mark:"}


class SlackMarkdown:
    name = "slack_md"
    def render(self, r: Report, product: dict[str, Any]) -> tuple[str, str]:
        m = r.memo
        flags = "\n".join(f"• *{f['flag']}* ({f['severity']}) — {', '.join(f['clauses'])}" for f in m.get("flags", []))
        sty = "\n".join(f"• {h['rule']} ({h['severity']}): {', '.join(h['evidence'])}" for h in r.style_check["rule_hits"] + r.style_check["place_name_hits"])
        actions = "\n".join(f"• {a}" for a in m.get("editor_decision_required", []))
        text = (f"{EMOJI[r.gate]} *{r.gate.upper()}* · {product['name']}\n*{r.draft.headline}*\n\n{r.draft.body}\n\n"
                f"*Etikk-flagg*\n{flags or '—'}\n\n*Språk og stil*\n{sty or '—'}\n\n*Redaktør må avgjøre*\n{actions or '—'}\n\n"
                f"_React :white_check_mark: approve · :pencil: revise · :x: kill · report #{r.id}_")
        return "text/slack-markdown", text


class Markdown:
    name = "markdown"
    # Templated genres (the digest) carry their real content in Draft.sections, which this
    # renderer used to drop on the floor. Norwegian keys render first, then the _en twin.
    ORDER = ("lead", "by_beat", "follow_ups", "watch", "unverified")
    TITLES = {"lead": "Hovedsak", "by_beat": "Etter felt", "follow_ups": "Oppfolging",
              "watch": "Til overvaking", "unverified": "Ubekreftet",
              # satire desk: editor-only matter, deliberately carried in sections rather than body
              "ikke_brukt": "Ikke brukt", "til_redaktoren": "Til redaktoren",
              "mechanics": "Mekanikk", "targets_hit": "Omtalte"}

    @staticmethod
    def _as_text(v: Any) -> str:
        """Sections are typed dict[str, str], but a model may nest a list or object. Flatten
        rather than raise: a malformed section must not lose the whole digest."""
        if isinstance(v, str):
            return v
        if isinstance(v, list):
            return "\n".join(Markdown._as_text(x) for x in v)
        if isinstance(v, dict):
            return "\n".join(f"**{k}**: {Markdown._as_text(x)}" for k, x in v.items())
        return str(v)

    def render(self, r: Report, product: dict[str, Any]) -> tuple[str, str]:
        m = r.memo
        out = [f"# {r.draft.headline}", "", f"**Gate:** {r.gate}  ·  **Product:** {product['name']}", "", r.draft.body, ""]
        sec = r.draft.sections or {}
        if sec.get("body_en"):          # bilingual genres: the whole digest again in English
            out += ["## English", ""]
            if sec.get("headline_en"):   # the Norwegian headline is the h1; this is its twin
                out += ["### " + self._as_text(sec["headline_en"]), ""]
            out += [self._as_text(sec["body_en"]), ""]
        keys = [k for k in self.ORDER if sec.get(k)]
        keys += [k for k in sec if k not in self.ORDER and k not in ("body_en", "headline_en")
                 and not k.endswith("_en") and sec.get(k)]
        for k in keys:
            out += [f"## {self.TITLES.get(k, k)}", "", self._as_text(sec[k]), ""]
            if sec.get(k + "_en"):
                out += ["**English**", "", self._as_text(sec[k + "_en"]), ""]
        out += ["## Etikkmemo"] + [f"- **{f['flag']}** ({f['severity']}): {f.get('assessment','')} — {', '.join(f['clauses'])}" for f in m.get("flags", [])]
        out += ["", "## Redaktør må avgjøre"] + [f"- {a}" for a in m.get("editor_decision_required", [])]
        return "text/markdown", "\n".join(out)


class JSONRenderer:
    name = "json"
    def render(self, r: Report, product: dict[str, Any]) -> tuple[str, str]:
        return "application/json", json.dumps({**r.to_row(), "id": r.id}, ensure_ascii=False, default=str)


for x in (SlackMarkdown(), Markdown(), JSONRenderer()):
    register("renderer", x)
