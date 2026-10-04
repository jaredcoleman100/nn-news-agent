"""Static browsable index over the archived items, English and Norwegian in parallel.

Reads the .md files core/archive.py wrote and emits one self-contained archive/index.html:
no build step, no server, no network. Open it from the shared drive and it works.

    PYTHONPATH=. python -c "from core import archive_site; print(archive_site.build())"

Regenerated at the end of every run.py pass, so it always matches what is on disk.

Every string the page shows exists in both languages. Item text comes from the archive files:
the source text as fetched, and the English twin core/translate.py produced. Both are shown at
once, side by side, rather than behind a toggle -- the archive is read by Norwegian-speaking and
English-speaking editors together, and a language switch hides half the material from whichever
one did not set it.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from core.archive import ARCHIVE_DIR, EN_MARK

SITE_FILE = ARCHIVE_DIR.parent / "index.html"

# Every chrome string, English first. Nothing on the page is single-language.
T = {
    "title":   ("News Archive - Northern Norway", "Nyhetsarkiv - Nord-Norge"),
    "search":  ("Search title and summary...", "Sok i tittel og sammendrag..."),
    "allsrc":  ("All sources", "Alle kilder"),
    "allday":  ("All days", "Alle dager"),
    "nohits":  ("No matches.", "Ingen treff."),
    "notitle": ("(no title)", "(uten tittel)"),
    "nobody":  ("No summary in the source - title only.",
                "Ingen sammendrag i kilden - bare tittel."),
    "pending": ("English not yet available for this item.",
                "Engelsk er ikke klar for denne saken enna."),
    "file":    ("file", "fil"),
    "allorg":  ("All outlets", "Alle redaksjoner"),
    "own":     ("NRK", "NRK"),
    "external":("Outside NRK", "Utenfor NRK"),
    "en":      ("English", "Engelsk"),
    "nb":      ("Norwegian", "Norsk"),
}

PAGE_HEAD = """<title>News Archive - Northern Norway / Nyhetsarkiv - Nord-Norge</title>
<style>
  :root {
    --bg: #fbfaf8; --panel: #ffffff; --ink: #1a1c1e; --muted: #6a7075;
    --line: #e4e2dd; --accent: #7a1f1f; --chip: #f0eee9;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #16181a; --panel: #1e2124; --ink: #e8e6e3; --muted: #9aa0a6;
      --line: #2e3237; --accent: #e08a8a; --chip: #262a2e;
    }
  }
  :root[data-theme="dark"] {
    --bg: #16181a; --panel: #1e2124; --ink: #e8e6e3; --muted: #9aa0a6;
    --line: #2e3237; --accent: #e08a8a; --chip: #262a2e;
  }
  body { background: var(--bg); color: var(--ink); padding-block: 28px; padding-left: 20px;
         padding-right: 20px; max-width: 1140px; margin: 0 auto;
         font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  h1 { font-size: 1.5rem; margin: 0 0 2px; letter-spacing: -0.01em; }
  h1 .alt { display: block; font-size: 0.95rem; font-weight: 500; color: var(--muted);
            letter-spacing: 0; margin-top: 2px; }
  .sub { color: var(--muted); font-size: 0.85rem; margin-bottom: 20px; }
  .sub .alt { display: block; }
  .controls { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 22px; }
  input[type=search], select {
    font: inherit; padding: 7px 10px; border: 1px solid var(--line); border-radius: 7px;
    background: var(--panel); color: var(--ink); min-width: 0; }
  input[type=search] { flex: 1 1 260px; }
  h2.day { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.07em;
           color: var(--muted); margin: 26px 0 10px; font-weight: 600; }
  .item { background: var(--panel); border: 1px solid var(--line); border-radius: 9px;
          padding: 13px 15px; margin-bottom: 9px; }
  /* English left, Norwegian right. Below 760px the two columns stack, English first, and each
     keeps its own language tag so a stacked pair is still unambiguous. */
  .pair { display: grid; grid-template-columns: 1fr 1fr; gap: 0 20px; }
  .col.nb { border-left: 1px solid var(--line); padding-left: 20px; }
  @media (max-width: 760px) {
    .pair { grid-template-columns: 1fr; gap: 16px 0; }
    .col.nb { border-left: 0; padding-left: 0; border-top: 1px solid var(--line);
              padding-top: 14px; }
  }
  .tag { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.08em;
         color: var(--muted); font-weight: 600; margin: 0 0 5px; }
  .item h3 { font-size: 1rem; margin: 0 0 5px; font-weight: 600; line-height: 1.35; }
  .item h3 a { color: var(--ink); text-decoration: none; }
  .item h3 a:hover { color: var(--accent); text-decoration: underline; }
  .meta { font-size: 0.78rem; color: var(--muted); display: flex; flex-wrap: wrap; gap: 7px;
          align-items: center; margin-top: 11px; padding-top: 10px;
          border-top: 1px solid var(--line); }
  .chip { background: var(--chip); border-radius: 20px; padding: 2px 9px; font-size: 0.74rem; }
  .body { margin: 7px 0 0; color: var(--muted); font-size: 0.89rem; }
  .empty { font-style: italic; opacity: 0.7; }
  .local { color: var(--muted); text-decoration: none; border-bottom: 1px dotted var(--line); }
  .none { color: var(--muted); padding: 30px 0; text-align: center; }
  .none .alt { display: block; }
</style>
"""


def _strip_headings(text: str) -> str:
    lines = [ln for ln in text.strip().splitlines() if not ln.startswith("# ")]
    return " ".join(ln.strip() for ln in lines if ln.strip())


def _parse(path: Path) -> dict[str, Any] | None:
    """Read one archived item back out of its front matter and its two body halves."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    # Anchor both delimiters to whole lines. A bare text.split("---", 2) ends the front matter
    # at the next "---" ANYWHERE in the file, and NRK slugs contain them --
    # `bil-har-kjort-i-fjellvegg---flys-til-unn-1.18022930` -- so the front matter was truncated
    # mid-URL and its remainder swallowed into the body. 35 files in the archive hit this.
    m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", text, re.DOTALL)
    if not m:
        return None
    fm, rest = m.group(1), text[m.end():]
    rec: dict[str, Any] = {}
    for line in fm.strip().splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            v = v.strip()
            # Values are written as JSON-quoted scalars so the front matter is valid YAML; older
            # files predate that and are bare. Accept both rather than rewriting the archive
            # before it can be read.
            if len(v) > 1 and v[0] == '"':
                try:
                    v = json.loads(v)
                except ValueError:
                    v = v.strip('"')
            rec[k.strip()] = v
    # The English twin sits below EN_MARK when translate.py has produced one. Splitting on the
    # marker rather than on "---" is why archive.py writes an HTML comment there: a second "---"
    # would read as the end of a new front matter block.
    rec.setdefault("org", "external")   # files written before core/outlets.py existed
    src, _, en = rest.partition(EN_MARK)
    rec["body"] = _strip_headings(src)
    rec["body_en"] = _strip_headings(en)
    rec["file"] = path.name
    rec["day"] = path.parent.name
    return rec


def collect() -> list[dict[str, Any]]:
    if not ARCHIVE_DIR.exists():
        return []
    out = [r for r in (_parse(p) for p in ARCHIVE_DIR.rglob("*.md")) if r]
    # newest day first, and within a day keep a stable title order
    out.sort(key=lambda r: (r.get("day", ""), r.get("title", "")), reverse=True)
    return out


def _pair(en: str, nb: str) -> str:
    """English, then the Norwegian under it in muted type. Used for the page chrome."""
    return html.escape(en) + '<span class="alt">' + html.escape(nb) + "</span>"


def _col(side: str, lang_tag: str, title: str, url: str, body: str, empty_note: str) -> str:
    """One language's half of an item card. `title`/`body`/`empty_note` arrive escaped."""
    head = ('<h3><a href="' + url + '" target="_blank" rel="noopener">' + title + "</a></h3>"
            if url else "<h3>" + title + "</h3>")
    blurb = ('<p class="body">' + body + "</p>" if body
             else '<p class="body empty">' + empty_note + "</p>")
    return ('<div class="col ' + side + '"><p class="tag">' + html.escape(lang_tag) + "</p>"
            + head + blurb + "</div>")


def build(hosted: bool = False, dest: Path | None = None) -> Path | None:
    """Write the index. `hosted=True` drops the links to local .md files, which cannot
    resolve once the page is served from object storage; every item's full text is already
    inline in the page, so nothing is lost by omitting them."""
    items = collect()
    if not items:
        return None
    sources = sorted({str(r.get("source") or "unknown") for r in items})
    days = sorted({str(r.get("day") or "") for r in items}, reverse=True)

    rows = []
    current_day = None
    for r in items:
        if r.get("day") != current_day:      # group under a date heading
            current_day = r.get("day")
            rows.append('<h2 class="day" data-day="' + html.escape(str(current_day))
                        + '">' + html.escape(str(current_day)) + "</h2>")
        url = html.escape(str(r.get("url") or ""))
        src = html.escape(str(r.get("source") or "unknown"))
        day = html.escape(str(r.get("day") or ""))
        lang = str(r.get("lang") or "").strip().lower()
        title_nb = html.escape(str(r.get("title") or "") or T["notitle"][1])
        body_nb = html.escape(str(r.get("body") or ""))
        if lang == "en":
            # A source already in English has no twin and needs none. Show the same text on both
            # sides rather than an apology, so the columns stay aligned down the page.
            title_en, body_en, pending = title_nb, body_nb, ""
        else:
            title_en = html.escape(str(r.get("title_en") or "") or T["notitle"][0])
            body_en = html.escape(str(r.get("body_en") or ""))
            # "Not yet translated" only when it genuinely is not. An item whose SOURCE has no body
            # -- a bare headline from a feed, which is most of the archive -- has nothing to
            # translate, so the English column should say what the Norwegian one says, not accuse
            # the translator of being behind. Front matter carries title_en, so its presence is
            # what distinguishes translated-with-no-body from untranslated.
            translated = bool(r.get("title_en"))
            has_source_body = bool(r.get("body"))
            pending = "" if (translated and not has_source_body) else (
                "" if r.get("body_en") else html.escape(T["pending"][0]))
        rel = html.escape(ARCHIVE_DIR.name + "/" + str(r.get("day")) + "/" + str(r.get("file")))
        langchip = ('<span class="chip">' + html.escape(lang) + "</span>") if lang else ""
        org = html.escape(str(r.get("org") or "external"))
        orgchip = ('<span class="chip">' + html.escape(T["own"][0]) + "</span>") if org == "own" else ""
        filelink = "" if hosted else (
            '<a class="local" href="' + rel + '">' + html.escape(T["file"][0] + " / " + T["file"][1]) + "</a>")
        rows.append(
            '<article class="item" data-source="' + src + '" data-day="' + day
            + '" data-org="' + org + '">'
            + '<div class="pair">'
            + _col("en", T["en"][0], title_en, url, body_en,
                   pending or html.escape(T["nobody"][0]))
            + _col("nb", T["nb"][1], title_nb, url, body_nb, html.escape(T["nobody"][1]))
            + "</div>"
            + '<div class="meta"><span class="chip">' + src + "</span>" + orgchip + langchip
            + "<span>" + day + "</span>" + filelink + "</div></article>")

    opts = "".join('<option value="' + html.escape(s) + '">' + html.escape(s) + "</option>"
                   for s in sources)
    dopts = "".join('<option value="' + html.escape(d) + '">' + html.escape(d) + "</option>"
                    for d in days)
    n_i, n_s, n_d = len(items), len(sources), len(days)

    script = (
        "const q=document.getElementById('q'),s=document.getElementById('src'),"
        "d=document.getElementById('day'),o=document.getElementById('org'),"
        "none=document.getElementById('none'),"
        "items=[...document.querySelectorAll('.item')];"
        # textContent spans both columns, so one query searches the Norwegian and the English
        # together and a reader finds a story under whichever language they typed.
        "function apply(){const t=q.value.toLowerCase(),sv=s.value,dv=d.value,ov=o.value;let n=0;"
        "for(const el of items){const ok=(!sv||el.dataset.source===sv)&&(!dv||el.dataset.day===dv)"
        "&&(!ov||el.dataset.org===ov)"
        "&&(!t||el.textContent.toLowerCase().includes(t));el.hidden=!ok;if(ok)n++;}"
        "none.hidden=n>0;"
        "for(const h of document.querySelectorAll('h2.day')){"
        "const vis=[...document.querySelectorAll('.item[data-day=\"'+h.dataset.day+'\"]')]"
        ".some(e=>!e.hidden);h.hidden=!vis;}}"
        "q.addEventListener('input',apply);s.addEventListener('change',apply);"
        "d.addEventListener('change',apply);o.addEventListener('change',apply);")

    body_html = (
        "<h1>" + _pair(*T["title"]) + "</h1>"
        + '<p class="sub">'
        + html.escape(f"{n_i} stories from {n_s} sources over {n_d} days. "
                      "Generated by nn-news-agent.")
        + '<span class="alt">'
        + html.escape(f"{n_i} saker fra {n_s} kilder over {n_d} dager. "
                      "Generert av nn-news-agent.")
        + "</span></p>"
        + '<div class="controls">'
        + '<input type="search" id="q" placeholder="'
        + html.escape(T["search"][0] + "  /  " + T["search"][1]) + '">'
        + '<select id="src"><option value="">'
        + html.escape(T["allsrc"][0] + " / " + T["allsrc"][1]) + "</option>" + opts + "</select>"
        + '<select id="day"><option value="">'
        + html.escape(T["allday"][0] + " / " + T["allday"][1]) + "</option>" + dopts + "</select>"
        + '<select id="org"><option value="">'
        + html.escape(T["allorg"][0] + " / " + T["allorg"][1]) + "</option>"
        + '<option value="external">' + html.escape(T["external"][0] + " / " + T["external"][1])
        + '</option><option value="own">' + html.escape(T["own"][0]) + "</option></select>"
        + "</div><div id=list>" + "".join(rows) + "</div>"
        + '<p class="none" id="none" hidden>' + html.escape(T["nohits"][0])
        + '<span class="alt">' + html.escape(T["nohits"][1]) + "</span></p>"
        + "<script>" + script + "</script>")

    target = dest or SITE_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(PAGE_HEAD + body_html, encoding="utf-8", newline="\n")
    return target
