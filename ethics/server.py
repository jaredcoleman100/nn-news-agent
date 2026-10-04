"""
Ethics MCP server for the Northern Norway news agent.

Design: deterministic and auditable. This server retrieves clauses from the
Norwegian press-ethics corpus (Vær Varsom-plakaten + NRK comments, NRK AI
guidelines, Redaktørplakaten, PFU rulings, regional supplement), runs
rule-based screens over a draft report, and returns a fixed memo schema.
It does NOT call a language model. The reporting agent writes the ethics
memo from what this server returns, so every memo is traceable to clauses.

Run:  python server.py            (stdio transport)
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

try:
    from mcp.server.mcpserver import MCPServer as FastMCP  # mcp >= 2
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP
from rank_bm25 import BM25Okapi
import style as _style

CORPUS_DIR = Path(__file__).parent / "corpus"
REGION_DIR = Path(os.environ.get("NEWSROOM_CONFIG", str(Path(__file__).resolve().parents[1] / "config" / "nord-norge")))

mcp = FastMCP("norsk-presseetikk")


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------

@dataclass
class Unit:
    id: str
    source: str
    text: str            # what the agent sees (official text if present, else summary/topic)
    tags: list[str]
    extra: dict[str, Any] = field(default_factory=dict)

    def searchable(self) -> str:
        return " ".join([self.id, self.text, " ".join(self.tags), self.extra.get("nrk_comment", "")]).lower()


def _load() -> list[Unit]:
    units: list[Unit] = []

    vvp = json.loads((CORPUS_DIR / "vvp.json").read_text(encoding="utf-8"))
    for c in vvp["clauses"]:
        text = c["text_nb"] or f"[official text not yet loaded] {c['topic']}"
        units.append(Unit(
            id=f"VVP {c['id']}", source="Vær Varsom-plakaten",
            text=text, tags=c["tags"] + [c["chapter"]],
            extra={"topic": c["topic"], "nrk_comment": c.get("nrk_comment", ""), "chapter": c["chapter"]},
        ))

    sup = json.loads((REGION_DIR / "supplements.json").read_text(encoding="utf-8"))
    for e in sup["entries"]:
        units.append(Unit(
            id=e["id"], source=e["source"],
            text=e["text_nb"] or e["summary_en"], tags=e["tags"],
            extra={"summary_en": e["summary_en"], "url": e.get("url", "")},
        ))

    pfu_path = CORPUS_DIR / "pfu_rulings.json"
    if pfu_path.exists():
        for r in json.loads(pfu_path.read_text(encoding="utf-8")).get("rulings", []):
            units.append(Unit(
                id=f"PFU {r['pfu_id']}", source="Pressens Faglige Utvalg",
                text=r["summary_en"], tags=[f"VVP {c}" for c in r.get("clauses_cited", [])] + [r.get("outcome", "")],
                extra=r,
            ))
    return units


UNITS = _load()
_BM25 = BM25Okapi([re.findall(r"\w+", u.searchable()) for u in UNITS])
_BY_ID = {u.id.lower(): u for u in UNITS}


def _search(query: str, k: int = 6) -> list[Unit]:
    toks = re.findall(r"\w+", query.lower())
    scores = _BM25.get_scores(toks)
    ranked = sorted(zip(scores, UNITS), key=lambda p: p[0], reverse=True)
    return [u for s, u in ranked[:k] if s > 0]


# ---------------------------------------------------------------------------
# Deterministic screens. Each returns (flag_id, clause_ids, evidence, severity)
# Severity: "block" = must resolve before publication; "review" = editor must
# decide; "note" = advisory.
# ---------------------------------------------------------------------------

SCREENS: list[dict[str, Any]] = [
    {
        "flag": "criminal_matter_identification",
        "clauses": ["VVP 4.7", "VVP 4.5", "NN-SUPPLEMENT-2"],
        "severity": "block",
        "pattern": r"\b(siktet|tiltalt|mistenkt|anmeldt|pågrepet|arrestert|dømt|etterforsk\w*|straffesak|charged|arrested|suspect\w*|indicted)\b",
        "why": "Text touches a criminal or blameworthy matter. Identification (name, photo, role, workplace, vessel, location) needs a justified information need. Check presumption of innocence.",
    },
    {
        "flag": "minor_involved",
        "clauses": ["VVP 4.8"],
        "severity": "block",
        # `elev\w*` and `ungdom\w*` removed 2026-09-29. VVP 4.8 protects an identifiable child from
        # the consequences of being portrayed; both words are collective policy terms in Norwegian
        # news and never identify anyone. Measured over all 17 briefs: 4 of 4 minor_involved flags
        # were false, and every one came from these two --
        #   «elever som sliter med grunnleggende ferdigheter» (school policy)
        #   «PISA-trenden blant elever» (statistics)
        #   «Natur og Ungdom anklager Nussir-gruven» -- the NAME OF AN NGO
        # -- while blocking the brief each time. A detector that fires on an organisation's name
        # teaches an editor to wave the flag through, which costs more than it buys.
        #
        # `barn` is kept even though it also produced a false positive («sjeldne tilstander hos
        # barn», childhood-dementia research): it is the word that actually denotes a child, and a
        # screen for VVP 4.8 without it is not a screen.
        "pattern": r"\b(barn|barna|mindreårig\w*|(1[0-7]|[1-9])[- ]?år(ing|inger|ig|\b)|gutt\w*|jent\w*|child\w*|minors\b|underage|teen\w*)\b",
        "why": "A child may be involved. Consider consequences for the child; identity is not revealed in family, child-welfare, or court matters.",
    },
    {
        "flag": "suicide",
        "clauses": ["VVP 4.9"],
        "severity": "block",
        "pattern": r"\b(selvmord\w*|selvdrap|tok sitt eget liv|suicide|self-harm)\b",
        "why": "Suicide or attempt. Publish only what meets a general information need; no method description.",
    },
    {
        "flag": "accusation_requires_reply",
        "clauses": ["VVP 4.14", "VVP 4.15"],
        "severity": "block",
        # `kritiser\w*` removed 2026-09-29. VVP 4.14 is the right of SIMULTANEOUS REPLY to a strong
        # factual accusation; criticism is not an accusation, and «kritiserer» is one of the most
        # common verbs in Norwegian political reporting. It produced the two weakest flags in the
        # archive -- an op-ed criticising a municipality's budgeting, and a party criticising
        # another party's district policy -- both ordinary political debate where nobody is accused
        # of anything. The terms that remain (anklage, beskylde, påstå, hevder at) all assert that
        # someone DID something, which is what triggers 4.14.
        #
        # The screen's true positives survive this: «Han er anklaget for storskala svindel og
        # maktmisbruk» and «Natur og Ungdom anklager Nussir-gruven» both match on `anklag\w*`.
        "pattern": r"\b(anklag\w*|beskyld\w*|påstå\w*|hevder at|accus\w*|alleg\w*|claims? that)\b",
        "why": "Strong accusations against a named or identifiable party trigger the right to simultaneous reply. Record whether the party was contacted and what they said.",
    },
    {
        "flag": "ethnicity_or_identity",
        "clauses": ["VVP 4.3", "NN-SUPPLEMENT-1"],
        "severity": "review",
        # `sam\w*` used to head this list and matched samtidig, samme, sammen, samarbeid, samfunn,
        # samlet, samferdsel, samordning, sameksistens -- i.e. ordinary Norwegian prose, so VVP 4.3
        # fired on nearly every report and the flag stopped carrying information (measured
        # 2026-09-14: a satire draft about fuel duty flagged on «Samtidig»). Enumerated Sámi terms
        # replace it. Note «samme»/«sammen» take a double m and never matched; the damage was
        # entirely from single-m compounds. Likewise `russ\w*` matched russ, russetid and russebuss
        # -- Norwegian graduation, not nationality -- so nationality is now spelled out.
        # Narrowed 2026-09-29. Institution, industry and country names removed: `sameting\w*`,
        # `samerett\w*`, `samepolitis\w*`, `samekultur\w*`, `sameland\w*`, `reindrift\w*` and
        # `russland`. VVP 4.3 asks whether ethnicity or nationality is RELEVANT and whether the
        # framing stigmatises. The Sámi Parliament is a parliament, reindeer herding is an
        # industry and Russland is a country -- naming any of them is not ethnic framing, it is
        # the subject.
        #
        # This desk's beats literally include "Sámi, Kven and Forest Finn rights" and "Arctic
        # security and the Russian border", so the screen was firing on the newsroom's own remit:
        # 12 of 17 briefs, 71%, on words like «Sametinget», «sametingsdirektøren» and
        # «reindriftsnæringen». A flag that appears on three briefs in four carries no information.
        #
        # The ethnic descriptors are kept -- samisk, samer, samene, sámi, kven, russisk, russer --
        # along with the vocabulary where stigmatising framing actually occurs: innvandrer, asyl,
        # muslim, immigrant, indigenous.
        "pattern": r"\b(sámi|sápmi|sami|samisk\w*|samer\w*|samene|samen|same"
                   r"|kven\w*|innvandr\w*|asyl\w*|asylum"
                   r"|muslim\w*|russisk\w*|russer\w*|indigenous|immigra\w*)\b",
        "why": "Ethnicity, nationality, or belief appears. Confirm it is relevant to the story and the framing is not stigmatizing.",
    },
    {
        "flag": "accident_or_death",
        "clauses": ["VVP 4.6"],
        "severity": "review",
        "pattern": r"\b(ulykke\w*|omkom\w*|død\w*|drept|forlis\w*|savnet|skred|accident\w*|died|dead|fatal\w*|missing)\b",
        "why": "Accident, death, or missing-person matter. Next of kin must not learn of it from the press; care in presentation.",
    },
    {
        "flag": "single_source_or_social_media",
        "clauses": ["VVP 3.2", "NRK-KI", "NN-SUPPLEMENT-3"],
        "severity": "review",
        "pattern": r"\b(facebook|tiktok|instagram|x\.com|twitter|reddit|ifølge en kilde|en kilde|anonymous source|according to a post|rumou?r\w*|rykte\w*)\b",
        "why": "Claim rests on social media or a single unnamed source. Verify against an independent source before publication.",
    },
    {
        "flag": "ai_generated_content",
        "clauses": ["NRK-KI", "VVP 3.2", "VVP 4.11"],
        "severity": "note",
        "pattern": r".",
        "why": "This report was drafted by an AI agent. Every factual claim must be verified by a human against a primary source before publication, and AI involvement disclosed per newsroom policy.",
    },
]


def _screen(text: str) -> list[dict[str, Any]]:
    hits = []
    for s in SCREENS:
        matches = re.findall(s["pattern"], text, flags=re.IGNORECASE)
        if matches:
            evidence = sorted({m if isinstance(m, str) else m[0] for m in matches})[:8]
            hits.append({
                "flag": s["flag"], "severity": s["severity"], "clauses": s["clauses"],
                "evidence": [] if s["flag"] == "ai_generated_content" else evidence, "why": s["why"],
            })
    return hits


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def search_ethics(query: str, k: int = 6) -> list[dict[str, Any]]:
    """Search the Norwegian press-ethics corpus (VVP with NRK comments, NRK AI
    guidelines, Redaktørplakaten, PFU rulings, Northern Norway supplement).
    Query in Norwegian or English. Returns ranked clauses/rulings."""
    return [asdict(u) for u in _search(query, k)]


@mcp.tool()
def get_clause(clause_id: str) -> dict[str, Any] | None:
    """Fetch one unit by id, e.g. 'VVP 4.7', 'NRK-KI', 'PFU 123/24'."""
    u = _BY_ID.get(clause_id.strip().lower())
    return asdict(u) if u else None


@mcp.tool()
def screen_report(report_text: str, headline: str = "", region: str = "Nord-Norge") -> dict[str, Any]:
    """Run deterministic ethics screens over a draft report and retrieve the
    clauses each flag rests on. Returns flags, retrieved clauses, and the
    required memo schema. The calling agent must then write the memo."""
    full = f"{headline}\n{report_text}"
    flags = _screen(full)
    needed_ids = {c for f in flags for c in f["clauses"]}
    clauses = {cid: asdict(_BY_ID[cid.lower()]) for cid in needed_ids if cid.lower() in _BY_ID}
    # Also retrieve by content so unusual cases surface clauses the screens miss.
    related = [asdict(u) for u in _search(full, 4) if u.id not in clauses]
    gate = "blocked" if any(f["severity"] == "block" for f in flags) else "review"
    return {
        "region": region,
        "publication_gate": gate,
        "flags": flags,
        "clauses": clauses,
        "related_units": related,
        "memo_schema": MEMO_SCHEMA,
        "instruction": (
            "Write the ethics memo strictly in memo_schema. For every flag, cite the clause id and state "
            "the concrete fact in the report that triggers it. Do not clear a 'block' flag; only a human "
            "editor may. Where the official clause text is marked as not yet loaded, say so."
        ),
    }


MEMO_SCHEMA = {
    "report_id": "string",
    "publication_gate": "blocked | review | clear (clear only if no flags at all, which should be rare)",
    "flags": [{
        "flag": "string", "severity": "block|review|note", "clauses": ["VVP x.y"],
        "trigger": "the specific sentence or fact in the report",
        "assessment": "how the clause applies here",
        "required_action": "what the editor must do or decide before publication",
    }],
    "identification_check": {
        "persons_identifiable": ["name or description"],
        "identifiers_used": ["name|photo|role|workplace|vessel|farm|municipality"],
        "justification_offered": "string or none",
    },
    "verification_ledger": [{
        "claim": "string", "source": "string", "source_type": "primary|official|media|social|single unnamed",
        "independently_verified": "yes|no|pending",
    }],
    "reply_status": [{"party": "string", "accusation": "string", "contacted": "yes|no", "response": "string"}],
    "ai_disclosure": "how the AI's role is to be disclosed",
    "editor_decision_required": ["plain-language list"],
}


@mcp.tool()
def style_check(report_text: str, headline: str = "", lang: str = "nb", check_spelling: bool = True) -> dict[str, Any]:
    """NRK house style + Norwegian rettskriving + official (Sámi/Kven) place names. Deterministic.
    Run after screen_report. lang: 'nb' or 'nn'."""
    return _style.style_check(report_text, headline, lang, check_spelling)


@mcp.tool()
def lookup_place(name: str) -> dict[str, Any]:
    """Live lookup of an official place name (all language forms) in Kartverket SSR."""
    return _style.lookup_place_ssr(name)


@mcp.tool()
def list_screens() -> list[dict[str, Any]]:
    """List the deterministic screens, their severities and clause bases, for audit."""
    return [{k: v for k, v in s.items() if k != "pattern"} for s in SCREENS]


@mcp.tool()
def corpus_status() -> dict[str, Any]:
    """Report which corpus units still lack official text — so the team knows what to paste in."""
    missing = [u.id for u in UNITS if u.text.startswith("[official text not yet loaded]")]
    return {"units": len(UNITS), "missing_official_text": missing}


@mcp.resource("ethics://memo-schema")
def memo_schema_resource() -> str:
    return json.dumps(MEMO_SCHEMA, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run()
