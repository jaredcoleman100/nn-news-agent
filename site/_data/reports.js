/**
 * The digests, read from the export core/reports_export.py writes.
 *
 * ARCHIVE_REPORTS points at it (default: ../archive/reports.json). Missing file is not an error:
 * an offline rebuild after a fresh checkout has no export yet, and a front page that says "no
 * digests" is more useful than a build that fails.
 *
 * Every digest gets a slug of `<date>-<product>-<id>`, derived from created_at and the row id
 * rather than from the headline. Headlines are Norwegian prose and get reworded between drafts, so
 * they make unstable URLs.
 *
 * The id is not decoration. `<date>-<product>` collides: 2026-09-17 has two daily digests (04:01
 * and 15:09, twelve claims and seventeen, different leads) because the desk was re-run that day,
 * and 2026-09-15 has three. They are distinct briefs, not revisions of one, so collapsing them
 * would silently drop published work -- and Eleventy refuses the build rather than let two
 * templates write one file, which is how this surfaced. Suffixing unconditionally, rather than only
 * on collision, keeps a URL stable: a later re-run cannot renumber an earlier brief's link.
 */
const fs = require("node:fs");
const path = require("node:path");

// The archive, for the URL -> archived-page join. Memoised inside items.js, so requiring it here
// costs nothing beyond the walk the build already does.
const items = require("./items.js");

const FILE = process.env.ARCHIVE_REPORTS
  || path.join(__dirname, "..", "..", "archive", "reports.json");

// The digest body is markdown from templates/daily_digest.md: "### Hovedsak" headings, "- " bullets
// and paragraphs. Rendering it as HTML here rather than shipping a markdown library keeps the build
// dependency-free (see eleventy.config.js -- Node would resolve a require against the drive, where
// there is no node_modules).
// INLINE FORMATTING LIVES IN _data/markdown.js, and is shared with the Norlit pieces.
//
// It used to live here too, as a second implementation that handled only **bold** -- correct when
// the brief templates forbade URLs in the body, wrong the moment they stopped obeying that. 605
// markdown links published as literal text before anyone noticed, because nothing made the two
// copies agree. Merged 2026-10-07. This file now owns only the BLOCK structure the digest template
// consumes; everything inside a line is markdown.js's job.
//
// Dependency-free still holds: that is a sibling file, not a package. See eleventy.config.js.
const inline = require("./markdown.js").inlineText;

function blocks(text) {
  const out = [];
  for (const raw of String(text || "").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      out.push({ kind: "h", level: Math.min(heading[1].length + 1, 4), html: inline(heading[2]) });
      continue;
    }
    const bullet = /^[-*•]\s+(.*)$/.exec(line);
    if (bullet) {
      const item = inline(bullet[1]);
      if (out.length && out[out.length - 1].kind === "ul") out[out.length - 1].items.push(item);
      else out.push({ kind: "ul", items: [item] });
      continue;
    }
    out.push({ kind: "p", html: inline(line) });
  }
  return out;
}

const PRODUCT = {
  "daily-digest": ["Morning brief", "Morgenbrief"],
  "satire-desk": ["Satire desk", "Satiredesken"],
  "international-brief": ["International brief", "Internasjonal brief"],
  "midterm-brief": ["US midterms brief", "Mellomvalgbrief"],
  "world-brief": ["World brief", "Verdensbrief"],
  "world-article": ["World article", "Verdensartikkel"],
  "editor-letter": ["Letter to the editor", "Brev til redaktøren"],
};

/** One entry per flag id. `block` wins over `review`; clauses and evidence are unioned. */
function dedupeFlags(flags) {
  const by = new Map();
  for (const f of flags) {
    const seen = by.get(f.flag);
    if (!seen) {
      by.set(f.flag, { ...f, clauses: [...(f.clauses || [])], evidence: [...(f.evidence || [])] });
      continue;
    }
    if (f.severity === "block") seen.severity = "block";
    for (const c of f.clauses || []) if (!seen.clauses.includes(c)) seen.clauses.push(c);
    for (const e of f.evidence || []) if (!seen.evidence.includes(e)) seen.evidence.push(e);
  }
  // block before review: the more serious note should be read first.
  return [...by.values()].sort((a, b) =>
    (a.severity === "block" ? 0 : 1) - (b.severity === "block" ? 0 : 1));
}


module.exports = function () {
  let raw = [];
  try {
    raw = JSON.parse(fs.readFileSync(FILE, "utf8"));
  } catch {
    return [];
  }

  // Every cited article's archived page, so a story card can offer the full text and its English
  // translation alongside the link to the original.
  //
  // Skipped entirely in the public build, which generates no item pages and so has no use for the
  // join: walking and parsing the 7,600-file archive tree cost 45 of the 46 seconds that build took
  // to emit 15 pages.
  const slugs = new Map();
  if (process.env.SITE_PUBLIC !== "1") {
    for (const it of items()) if (it.url) slugs.set(it.url, it.slug);
  }

  // The daily letter to the editor publishes. It came off the public site for an hour on
  // 2026-10-01 ("delete the current letter until we draft a better") and went back on once the
  // rewrite existed: a short morning note -- greeting, three or four SOURCED facts from the day's
  // items, one stanza -- in place of four paragraphs of caveats. The two drafts in the old format
  // were deleted rather than left to publish alongside it.
  //
  // What makes it publishable at all is in templates/editor_letter.md: it knows her name and that
  // she edits this desk, and is forbidden to imply more. If it ever starts referring to her life,
  // her mood or her opinions, it comes off the public site again rather than being edited to look
  // harmless.
  return raw.map((r) => {
    const day = String(r.created_at || "").slice(0, 10);
    const stories = (r.stories || []).map((s) => ({ ...s, itemSlug: slugs.get(s.url) || "" }));
    return {
      ...r,
      day,
      slug: `${day}-${r.product}-${r.id}`,
      productName: PRODUCT[r.product] || [r.product, r.product],
      blocks: blocks(r.body),
      blocksEn: blocks(r.body_en),
      // Split for the page, because the editorial rule is that the lead must come from outside
      // NRK and NRK's own coverage is listed as overlap. The site should show the same shape the
      // digest template enforces.
      external: stories.filter((s) => s.org !== "own"),
      own: stories.filter((s) => s.org === "own"),
      // Nothing is withheld any more (2026-09-28, by instruction): a brief the ethics screens
      // flagged is published WITH A WARNING rather than held back. `warn` is the flags worth
      // showing a reader -- `note` is excluded here because the only note-level flag is the
      // AI-disclosure one, which every brief already carries in its own footer, and repeating it
      // as a warning on all fifteen would train people to ignore the banner.
      //
      // `held` used to live here and drove a "Held / Holdt" chip. It is gone: the outbox hold was
      // never switched on, so the chip claimed something that was not true of a single brief.
      //
      // Deduplicated by flag id: the screens emit one object per MATCH, not per rule, so a brief
      // that trips `criminal_matter_identification` on two different words produced two identical
      // warning lines. Clauses and evidence are merged so nothing is lost by collapsing them.
      warn: dedupeFlags((r.flags || [])
        .filter((f) => f.severity === "review" || f.severity === "block")),
    };
  });
};
