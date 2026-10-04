"""Norwegian press ethics (VVP + NRK + regional supplements) and NRK style, as an EthicsCode plugin.
Wraps ethics/server.py and ethics/style.py in-process. Genre overlays let a product weight or add screens."""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Any
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ethics"))
import server as _ethics   # noqa: E402
import style as _style     # noqa: E402
from core.registry import register
from core.schema import Draft

GENRE_OVERLAYS: dict[str, dict[str, Any]] = {
    # screens whose severity is raised for a genre, and extra clauses always retrieved
    "digest": {"raise": {}, "always_clauses": ["VVP 4.4"]},
    "document_story": {"raise": {"accusation_requires_reply": "block"}, "always_clauses": ["VVP 2.2", "VVP 3.2", "VVP 4.4"]},
    "data": {"raise": {}, "always_clauses": ["VVP 4.4", "VVP 3.2"]},
    # Research: overreach beyond the abstract (4.4), a single study as consensus (3.2),
    # and findings blurred with the authors' policy recommendations (4.2).
    "research": {"raise": {}, "always_clauses": ["VVP 4.4", "VVP 3.2", "VVP 4.2"]},
    "regional_report": {"raise": {}, "always_clauses": []},
    # Satire is not exempt from VVP; PFU practice grants it wider latitude in TONE, not in FACT.
    # So the overlay loosens nothing and raises the four screens where a joke fails differently
    # from a report: a report that gets these wrong is corrected, a joke that gets them wrong was
    # never worth running. VVP 1.5 is always retrieved because it is the affirmative case for the
    # genre -- satire aimed at power is the press's job -- and the memo should reason from it
    # rather than treat every flag as a reason to soften.
    "satire": {
        "raise": {
            "accusation_requires_reply": "block",      # VVP 4.14 -- a punchline is not a right of reply
            "single_source_or_social_media": "block",  # an unverified premise is the whole failure mode
        },
        # `ethnicity_or_identity` is deliberately NOT raised, despite VVP 4.3 being the line this
        # genre most needs to respect. Its pattern in ethics/server.py starts `sam\w*`, which matches
        # samtidig, samme, sammen, samarbeid, samfunn, samlet, samferdsel -- so it fires on ordinary
        # Norwegian prose, not on ethnicity. Measured 2026-09-14: a joke purely about fuel duty and
        # the fiscal rule was flagged on the word «Samtidig». Raising a detector that noisy to `block`
        # blocks every draft and teaches the editor to wave the flag through, which costs more safety
        # than it buys. It stays at `review` -- and since `publishes: false` and `gate_required` mean
        # a human reads everything regardless, `review` already guarantees the only control that works.
        # The real VVP 4.3 controls are the template's off-limits section and the editor.
        # `minor_involved` is likewise left alone: it is already `block` by default in SCREENS.
        "always_clauses": ["VVP 1.5", "VVP 3.7", "VVP 4.1", "VVP 4.3", "VVP 4.14"],
    },
}


class VVPCode:
    name = "vvp"
    version = "vvp-2024-01-01+nrk+nn-supp-1"

    def screen(self, draft: Draft, product: dict[str, Any]) -> dict[str, Any]:
        r = _ethics.screen_report(draft.body, headline=draft.headline, region=product.get("region", ""))
        ov = GENRE_OVERLAYS.get(product["ethics"].get("genre", "regional_report"), {})
        for f in r["flags"]:
            if f["flag"] in ov.get("raise", {}):
                f["severity"] = ov["raise"][f["flag"]]
        for cid in ov.get("always_clauses", []):
            u = _ethics._BY_ID.get(cid.lower())
            if u and cid not in r["clauses"]:
                r["clauses"][cid] = _ethics.asdict(u)
        if any(f["severity"] == "block" for f in r["flags"]):
            r["publication_gate"] = "blocked"
        r["genre_overlay"] = product["ethics"].get("genre")
        return r

    def style(self, draft: Draft, product: dict[str, Any]) -> dict[str, Any]:
        return _style.style_check(draft.body, headline=draft.headline, lang=product.get("lang", "nb"),
                                  check_spelling=product.get("check_spelling", False))


register("code", VVPCode())
