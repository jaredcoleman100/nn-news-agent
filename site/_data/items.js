/**
 * Every archived item, read straight from the markdown tree core/archive.py writes.
 *
 * ARCHIVE_ITEMS points at that tree (default: ../archive/items relative to the repo). The files
 * live on the shared drive; this toolchain does not.
 *
 * No YAML dependency on purpose. core/archive.py writes front matter as strict
 * `key: <json-string>` lines -- a JSON double-quoted string is also a valid YAML scalar, which is
 * how the archive became parseable at all (Norwegian headlines are full of colons, and unquoted
 * they read as nested mappings). Since every value is JSON, JSON.parse per line is exact, and the
 * build gains no dependency that would have to live next to the drive.
 */
const fs = require("node:fs");
const path = require("node:path");

const ROOT = process.env.ARCHIVE_ITEMS
  || path.join(__dirname, "..", "..", "archive", "items");

// Separates the source text from its English twin inside an archived item. Must match
// core/archive.py's EN_MARK exactly.
const EN_MARK = "<!-- en -->";

// Line-anchored: a bare split on "---" ends the front matter at the next "---" ANYWHERE in the
// file, and NRK slugs contain them (bil-har-kjort-i-fjellvegg---flys-til-unn-1.18022930).
const FRONT_MATTER = /^---[ \t]*\r?\n([\s\S]*?)\r?\n---[ \t]*\r?\n?/;

function stripHeadings(text) {
  return (text || "")
    .split(/\r?\n/)
    .filter((line) => !line.startsWith("# "))
    .map((line) => line.trim())
    .filter(Boolean)
    .join("\n");
}

function parseFile(file) {
  const raw = fs.readFileSync(file, "utf8");
  const match = FRONT_MATTER.exec(raw);
  if (!match) return null;

  const rec = {};
  for (const line of match[1].split(/\r?\n/)) {
    const at = line.indexOf(":");
    if (at === -1) continue;
    const key = line.slice(0, at).trim();
    const value = line.slice(at + 1).trim();
    try {
      rec[key] = JSON.parse(value);
    } catch {
      // Pre-2026-09-17 files were written unquoted. Keep them readable rather than dropping them.
      rec[key] = value.replace(/^"|"$/g, "");
    }
  }

  const rest = raw.slice(match[0].length);
  const cut = rest.indexOf(EN_MARK);
  const source = stripHeadings(cut === -1 ? rest : rest.slice(0, cut));
  const english = cut === -1 ? "" : stripHeadings(rest.slice(cut + EN_MARK.length));

  const day = path.basename(path.dirname(file));
  const slug = path.basename(file, ".md");

  return {
    slug,
    day,
    title: rec.title || "(uten tittel)",
    titleEn: rec.title_en || "",
    url: rec.url || "",
    source: rec.source || "unknown",
    // "own" = this newsroom's outlet (NRK), "external" = everyone else. See core/outlets.py.
    org: rec.org === "own" ? "own" : "external",
    lang: (rec.lang || "").toLowerCase(),
    publishedAt: rec.published_at || "",
    body: source,
    bodyEn: english,
    // An item whose source is already English needs no twin; show the same text both sides rather
    // than an apology, so the two columns stay aligned down the page.
    get englishIsSource() {
      return this.lang === "en";
    },
  };
}

function walk(dir) {
  const out = [];
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const e of entries) {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...walk(full));
    else if (e.isFile() && e.name.endsWith(".md")) out.push(full);
  }
  return out;
}

let cached = null;

module.exports = function () {
  // Memoised: the config requires this module to build the outlet collections, and Eleventy calls
  // it again as global data. Without this the 2300-file tree is walked and parsed twice.
  if (cached) return cached;

  // The public build renders no page that reads an item: the archive templates are ignored and the
  // front page's category strip is behind site.internal. Eleventy still loads every _data file as
  // global data, though, so the guard has to be here rather than only at the call sites -- reading
  // 7,600 files to emit 15 pages was the whole cost of that build.
  if (process.env.SITE_PUBLIC === "1") {
    cached = [];
    return cached;
  }
  const files = walk(ROOT);
  const items = files.map(parseFile).filter(Boolean);
  // Newest day first, stable title order inside a day -- same ordering as the single-page index,
  // so the two surfaces cannot disagree about what "latest" means.
  items.sort((a, b) => (b.day + b.title).localeCompare(a.day + a.title, "nb"));

  // One page per URL. The archive can hold the same story twice: the filename is
  // `<title-slug>--<url-hash>`, so when two feeds carry one URL under different headlines (NRK
  // Nordland and NRK Troms og Finnmark both syndicating, or a revised headline) the hash matches
  // and the slug does not, giving two files. Rare -- 2 of 2369 today -- but it double-counts on
  // category pages, where each copy picks up the same hits. Newest wins, since the sort above is
  // already newest-first.
  const seen = new Set();
  const unique = items.filter((i) => !i.url || (!seen.has(i.url) && seen.add(i.url)));

  cached = unique;
  return unique;
};
