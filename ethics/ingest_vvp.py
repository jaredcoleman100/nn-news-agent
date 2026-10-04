"""
Fill corpus/vvp.json with the official Vær Varsom-plakaten text from presse.no.

    pip install requests beautifulsoup4
    python ingest_vvp.py                # bokmål from presse.no
    python ingest_vvp.py --url URL      # any page carrying the numbered clauses
    python ingest_vvp.py --html saved.html   # from a page you saved in the browser

presse.no is a client-rendered Next.js/Sanity site, so the script tries three
things in order: (1) rendered HTML text, (2) the __NEXT_DATA__ JSON blob,
(3) any Sanity portable-text arrays it can find. If all fail, save the page
from your browser (Ctrl+S, "Webpage, complete") and pass --html.

The parser looks for clause numbers of the form 1.1 … 4.17 at the start of a
block and takes everything up to the next clause number. It never rewrites
text; it only splits it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

CORPUS = Path(__file__).parent / "corpus" / "vvp.json"
DEFAULT_URL = "https://www.presse.no/vaer-varsom-plakaten"
UA = {"User-Agent": "Mozilla/5.0 (ethics-mcp ingest; contact newsroom)"}

CLAUSE_RE = re.compile(r"(?<![\d.])([1-4]\.\d{1,2})\.?\s+")


def _walk_strings(obj, out: list[str]) -> None:
    """Collect every string leaf in a JSON structure, in order."""
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        # Sanity portable text: {"_type":"block","children":[{"text":...}]}
        if obj.get("_type") == "block" and "children" in obj:
            out.append("".join(c.get("text", "") for c in obj["children"]))
        else:
            for v in obj.values():
                _walk_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_strings(v, out)


def candidate_texts(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    texts: list[str] = []

    main = soup.find("main") or soup.body or soup
    texts.append(main.get_text("\n", strip=True))

    nd = soup.find("script", id="__NEXT_DATA__")
    if nd and nd.string:
        try:
            leaves: list[str] = []
            _walk_strings(json.loads(nd.string), leaves)
            texts.append("\n".join(leaves))
        except json.JSONDecodeError:
            pass

    for s in soup.find_all("script"):
        if s.string and '"_type":"block"' in s.string:
            for m in re.finditer(r"\[\s*\{\s*\"_type\"\s*:\s*\"block\".*?\]", s.string, flags=re.S):
                try:
                    leaves = []
                    _walk_strings(json.loads(m.group(0)), leaves)
                    texts.append("\n".join(leaves))
                except json.JSONDecodeError:
                    continue
    return texts


def split_clauses(text: str) -> dict[str, str]:
    text = re.sub(r"[ \t]+", " ", text)
    parts = CLAUSE_RE.split(text)
    # parts = [preamble, id, body, id, body, ...]
    clauses: dict[str, str] = {}
    for i in range(1, len(parts) - 1, 2):
        cid, body = parts[i], parts[i + 1]
        body = body.strip()
        # Cut trailing chapter headings that precede the next clause.
        body = re.split(r"\n\s*[1-4]\.\s+(?=[A-ZÆØÅ])", body)[0].strip()
        if cid not in clauses and len(body) > 10:
            clauses[cid] = body
    return clauses


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--html", help="path to a saved HTML file instead of fetching")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.html:
        html = Path(args.html).read_text(encoding="utf-8", errors="ignore")
    else:
        r = requests.get(args.url, headers=UA, timeout=30)
        r.raise_for_status()
        html = r.text

    best: dict[str, str] = {}
    for t in candidate_texts(html):
        got = split_clauses(t)
        if len(got) > len(best):
            best = got

    if not best:
        print("No clauses found. The page is probably client-rendered; save it from your browser and pass --html.", file=sys.stderr)
        return 1

    data = json.loads(CORPUS.read_text(encoding="utf-8"))
    filled, missing = 0, []
    for c in data["clauses"]:
        if c["id"] in best:
            c["text_nb"] = best[c["id"]]
            filled += 1
        else:
            missing.append(c["id"])
    data["_meta"]["ingested_from"] = args.html or args.url

    print(f"Parsed {len(best)} clauses; filled {filled}/{len(data['clauses'])}.")
    if missing:
        print("Still missing:", ", ".join(missing))
    if args.dry_run:
        for cid in list(best)[:3]:
            print(f"\n{cid}: {best[cid][:120]}…")
        return 0
    CORPUS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {CORPUS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
