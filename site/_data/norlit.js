/**
 * The literature magazine: the daily piece from the `norlit` project next door.
 *
 * Reads norlit's OUTBOX, which is the agreed interface -- norlit/INTEGRATION.md. An earlier
 * version of this file read `innlegg/` and `barn/` markdown directly; that was two contracts for
 * one handoff, and the outbox is the one norlit actually writes. This reads it and never writes
 * to it, mirroring norlit's read-only treatment of nn-news-agent's archive.
 *
 * THE GATE
 * norlit sets `gate` itself, having checked every quotation word for word against its own corpus,
 * that the front matter is complete, that an English version exists, and that this desk's own
 * screen did not block it.
 *
 *   gate: "publish"  -> appears on the site.
 *   gate: "review"   -> does NOT appear. Held, counted, and named on the magazine index so a
 *                       held piece is visible as held rather than silently missing.
 *
 * This is a deliberate exception to the desk's rule that nothing publishes without an editor, and
 * it is narrow: it applies to these literature pieces only, and only to `gate: "publish"`. Jared
 * decided it (2026-10-01) and norlit's own checks are the control that earns it.
 *
 * Not everything in the contract is done. Pushing `gate: "review"` pieces into the Supabase review
 * queue as rows with editor_decision NULL is still outstanding -- see the note in the magazine
 * template. Until then a held piece is visible here but not actionable from the review page.
 */
const fs = require("node:fs");
const path = require("node:path");

// site/_data -> site -> nn-news-agent -> Norway -> norlit/outbox
// WHERE THE PIECES COME FROM, in order of preference:
//   1. NORLIT_OUTBOX, if set.
//   2. ../../../norlit/outbox -- norlit's live outbox, when its repo sits beside this one on the
//      shared drive. This is the agreed interface (norlit/INTEGRATION.md) and the only source
//      that is ever up to date.
//   3. vendor/norlit-outbox -- a committed snapshot, for builds that have no sibling repo. A
//      GitHub Actions runner clones THIS repo and nothing else, and until 2026-10-04 that meant
//      readdirSync threw, the catch below swallowed it, and the site published with the entire
//      literature section silently missing. A snapshot that is a week stale is a far smaller
//      failure than seventeen pieces vanishing with nothing in the log.
const CANDIDATES = [
  process.env.NORLIT_OUTBOX,
  path.join(__dirname, "..", "..", "..", "norlit", "outbox"),
  path.join(__dirname, "..", "..", "vendor", "norlit-outbox"),
].filter(Boolean);

const OUTBOX = CANDIDATES.find((d) => {
  try { return fs.statSync(d).isDirectory(); } catch { return false; }
}) || CANDIDATES[CANDIDATES.length - 1];

const KINDS = {
  essay: { name: ["Essay", "Essay"],
           note: ["A scene from Norwegian literature, held against a story in the briefs.",
                  "En scene fra norsk litteratur, holdt opp mot en sak i briefene."] },
  barn:  { name: ["For younger readers", "For yngre lesere"],
           note: ["A strange story from folklore, retold for readers aged 9-12.",
                  "En rar historie fra folkediktningen, gjenfortalt for lesere 9-12 år."] },
  historie: { name: ["The king in Norwegian literature", "Kongen i norsk litteratur"],
           note: ["A weekly chapter in a literary history of the idea of the king in Norway.",
                  "Et ukentlig kapittel i en litteraturhistorie om kongetanken i Norge."] },
  vise:  { name: ["Song", "Vise"],
           note: ["A song in classic Norwegian style, built from images verified in the library.",
                  "En vise i klassisk norsk stil, bygd på bilder verifisert i biblioteket."] },
};

/** Chapter number: the `chapter` field when norlit sends it, else the "... N:" in the title. */
function chapterNo(p) {
  if (Number.isFinite(p.chapter)) return p.chapter;
  const m = /\s(\d+)\s*:/.exec(p.title || "");
  return m ? Number(m[1]) : 0;
}

let cached = null;

module.exports = function () {
  if (cached) return cached;

  let files = [];
  try {
    files = fs.readdirSync(OUTBOX).filter((f) => f.endsWith(".json"));
  } catch {
    files = [];                      // norlit not beside this repo, or no run yet. Not an error.
  }

  const all = [];
  for (const f of files) {
    let p;
    try {
      p = JSON.parse(fs.readFileSync(path.join(OUTBOX, f), "utf8"));
    } catch {
      continue;                      // a half-written file mid-run; the next build picks it up
    }
    if (!p || !p.id || !p.body) continue;
    const kind = KINDS[p.kind] ? p.kind : "essay";
    all.push({
      ...p,
      kind,
      kindName: KINDS[kind].name,
      kindNote: KINDS[kind].note,
      date: String(p.date || "").slice(0, 10),
      sources: p.sources || [],
      news: p.news || [],
      gateReasons: p.gate_reasons || [],
      // Series fields, on `historie` pieces only.
      chapter: Number.isFinite(p.chapter) ? p.chapter : null,
      summary: p.summary || "",
      summaryEn: p.summary_en || "",
      // Quotation counts reach the template so the notice can distinguish "a regex tripped" from
      // "a quotation could not be found in its source" -- very different things to a reader, and
      // the distinction I got wrong when I argued against publishing these at all.
      quotations: (p.checks || {}).quotations || 0,
      failing: (p.checks || {}).failing || 0,
      published: p.gate === "publish",
    });
  }
  // `chapter` is not in the JSON yet (norlit is adding it), so the series orders by date for
  // now -- oldest first, because a serial reads forwards. Everything else is newest first.
  all.sort((a, b) => (b.date + b.id).localeCompare(a.date + a.id, "nb"));

  // Everything publishes. `published` stays on each piece so the template can mark the ones that
  // carry a reservation, and `flagged` is the subset, for counting.
  cached = {
    all,
    flagged: all.filter((p) => !p.published),
    total: all.length,
    heldCount: all.filter((p) => !p.published).length,
    strands: Object.keys(KINDS)
      .map((k) => ({
        kind: k, ...KINDS[k],
        // The series orders by the chapter number in its title ("... 1:", "... 2:"), because
        // both chapters so far carry the same date and date-order cannot separate them. norlit is
        // adding a `chapter` field; this prefers it the moment it appears and falls back to the
        // title until then. A serial reads forwards, so ascending.
        posts: k === "historie"
          ? all.filter((p) => p.kind === k).slice().sort((a, b) => chapterNo(a) - chapterNo(b))
          : all.filter((p) => p.kind === k),
      }))
      .filter((s) => s.posts.length)
      .map((s) => ({ ...s, count: s.posts.length })),
    latest: all[0] || null,
    // The king series as a reading order, each chapter knowing its neighbours so a chapter page
    // can offer previous/next without recomputing the sort. Chapters not yet in the outbox are
    // simply absent -- the contents page fills in as they arrive, and `planned` is what the
    // literature desk said is coming, so the page can show the shape of the whole thing.
    // chapter 0 is the whole series condensed into one essay, not a chapter before chapter 1. It
    // is kept OUT of the numbered sequence: in the contents it is the essay version at the top,
    // and it is not in any chapter's previous/next, because "previous: 0" would send a reader
    // from chapter 1 back into a summary of the thing they have just started.
    seriesEssay: all.find((p) => p.kind === "historie" && chapterNo(p) === 0) || null,
    series: (() => {
      // Number FIRST, then link. Spreading the raw pieces into prev/next left them without `no`,
      // so a chapter page rendered "← . Kongen i norsk litteratur 1:" with an empty number.
      const ch = all.filter((p) => p.kind === "historie" && chapterNo(p) > 0)
                    .slice()
                    .sort((a, b) => chapterNo(a) - chapterNo(b))
                    .map((p) => ({ ...p, no: chapterNo(p) }));
      return ch.map((p, i) => ({
        ...p,
        prev: i > 0 ? ch[i - 1] : null,
        next: i < ch.length - 1 ? ch[i + 1] : null,
      }));
    })(),
  };
  return cached;
};
