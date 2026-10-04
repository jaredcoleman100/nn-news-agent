"""
Style layer: NRK house rules, Norwegian rettskriving, official place names.

Deterministic like the ethics screens. Three checks:
  1. rules      — corpus/style_rules.json (numbers, quotes, dates, abbreviations, AI marking, ...)
  2. places     — corpus/place_names.json, with Kartverket SSR lookup for unknown names
  3. spelling   — Språkrådet/UiB ordbok API (ord.uib.no) for words not found in Bokmålsordboka/Nynorskordboka

Network calls are optional and fail soft: if the API is unreachable the check reports
'unverified' rather than inventing a result.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

CORPUS_DIR = Path(__file__).parent / "corpus"
REGION_DIR = Path(os.environ.get("NEWSROOM_CONFIG", str(Path(__file__).resolve().parents[1] / "config" / "nord-norge")))
RULES = json.loads((CORPUS_DIR / "style_rules.json").read_text(encoding="utf-8"))
PLACES = json.loads((REGION_DIR / "place_names.json").read_text(encoding="utf-8"))["places"]

ORDBOK_API = "https://ord.uib.no/api/articles?w={word}&dict={dict}&scope=ei"
SSR_API = "https://api.kartverket.no/stedsnavn/v1/navn?sok={name}&fuzzy=false&utkoordsys=4258&treffPerSide=5"

NUMBER_WORDS_NB = ["null", "én", "to", "tre", "fire", "fem", "seks", "sju", "åtte", "ni", "ti", "elleve", "tolv"]


# ---------------------------------------------------------------------------
# 1. House rules
# ---------------------------------------------------------------------------

def _rule_hits(text: str, body_only: str) -> list[dict[str, Any]]:
    hits = []
    for r in RULES["rules"]:
        kind = r["check"]
        found: list[str] = []
        if kind == "regex":
            found = [m.group(0) for m in re.finditer(r["pattern"], text)]
        elif kind == "wordlist":
            for w in r["words"]:
                if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text, flags=re.IGNORECASE):
                    found.append(w)
        elif kind == "small_numbers":
            # digits 0-12 in prose; skip sentences that also carry ≥13 (even-out rule) or an abbreviated unit
            for sent in re.split(r"(?<=[.!?])\s+", body_only):
                if re.search(r"\b(1[3-9]|[2-9]\d|\d{3,})\b", sent) or re.search(r"\b\d+\s?(kg|km|kr|kl|m|g|l)\b", sent):
                    continue
                for m in re.finditer(r"(?<![\d.,:/–-])\b([0-9]|1[0-2])\b(?![\d.,:/%–-]|\. )", sent):
                    found.append(m.group(0))
        elif kind == "ai_marking":
            if r["required_phrase"] not in text.lower():
                found = ["(missing)"]
        if found:
            hits.append({"rule": r["id"], "severity": r["severity"], "evidence": sorted(set(found))[:8], "message": r["message"]})
    return hits


# ---------------------------------------------------------------------------
# 2. Place names
# ---------------------------------------------------------------------------

def _place_hits(text: str, lang: str) -> list[dict[str, Any]]:
    hits = []
    for p in PLACES:
        forms = {k: v for k, v in p.items() if k in ("nb", "se", "smj", "fkv") and v}
        present = {k: v for k, v in forms.items() if re.search(rf"(?<!\w){re.escape(v)}(?!\w)", text)}
        if not present:
            continue
        sami = {k: v for k, v in forms.items() if k in ("se", "smj")}
        if p.get("sami_admin_area") and sami and not any(k in present for k in sami):
            hits.append({"rule": "sami_form_on_first_mention", "severity": "advise",
                         "evidence": [p["nb"]],
                         "message": f"{p['nb']} is in the Sámi language administrative area; give the Sámi form on first mention: "
                                    f"{' / '.join(sami.values())}" + (f" (official municipality name: {p['municipality_official']})" if p.get("municipality_official") else "")})
        if any(k in present for k in sami) and "nb" not in present and lang == "nb":
            hits.append({"rule": "norwegian_form_missing", "severity": "advise", "evidence": list(present.values()),
                         "message": f"Sámi form used without the Norwegian form {p['nb']} in Norwegian-language text; give both on first mention."})
    return hits


def lookup_place_ssr(name: str) -> dict[str, Any]:
    """Live lookup in Kartverket SSR. Returns official names by language, or {'status': 'unverified'}."""
    try:
        import httpx
        r = httpx.get(SSR_API.format(name=name), timeout=10)
        r.raise_for_status()
        data = r.json()
        out = []
        for n in data.get("navn", []):
            out.append({"navn": n.get("skrivemåte"), "språk": n.get("språk"), "type": n.get("navneobjekttype"),
                        "kommune": [k.get("kommunenavn") for k in n.get("kommuner", [])]})
        return {"status": "ok", "results": out}
    except Exception as e:  # noqa: BLE001
        return {"status": "unverified", "error": str(e)}


# ---------------------------------------------------------------------------
# 3. Spelling
# ---------------------------------------------------------------------------

@lru_cache(maxsize=4096)
def _in_ordbok(word: str, dict_: str) -> bool | None:
    """True/False if the ordbok API answers; None if unreachable."""
    try:
        import httpx
        r = httpx.get(ORDBOK_API.format(word=word, dict=dict_), timeout=8)
        r.raise_for_status()
        d = r.json()
        return bool(d.get("articles", {}).get(dict_))
    except Exception:  # noqa: BLE001
        return None


def _spelling_hits(text: str, lang: str, max_words: int = 60) -> dict[str, Any]:
    dict_ = "bm" if lang == "nb" else "nn"
    known_names = {v for p in PLACES for k, v in p.items() if k in ("nb", "se", "smj", "fkv") and v}
    # lower-case tokens only: proper nouns are handled by the place check and the editor
    tokens = [t for t in re.findall(r"\b[a-zæøåáčđŋšŧž]{4,}\b", text) if t not in known_names]
    tokens = sorted(set(tokens))[:max_words]
    unknown, unverified = [], False
    for t in tokens:
        r = _in_ordbok(t, dict_)
        if r is None:
            unverified = True
            break
        if not r:
            unknown.append(t)
    return {"checked": len(tokens), "unknown_words": unknown, "status": "unverified (ordbok API unreachable)" if unverified else "ok",
            "note": "Unknown ≠ wrong: compounds, inflections, and Sámi loans are often absent from the ordbok. Editor judgment."}


# ---------------------------------------------------------------------------

def style_check(report_text: str, headline: str = "", lang: str = "nb", check_spelling: bool = True) -> dict[str, Any]:
    text = f"{headline}\n{report_text}"
    rules = _rule_hits(text, report_text)
    places = _place_hits(text, lang)
    spelling = _spelling_hits(report_text, lang) if check_spelling else {"status": "skipped"}
    fixes = [h for h in rules + places if h["severity"] == "fix"]
    return {
        "lang": lang,
        "language_rule": RULES["language"]["rule"],
        "verdict": "fix_required" if fixes else "ok",
        "rule_hits": rules,
        "place_name_hits": places,
        "spelling": spelling,
        "sami_practice": RULES["sami_place_name_practice"],
    }
