/**
 * News categories: the scored hits, grouped by beat, joined to the archived items.
 *
 * `archive/hits.json` is written by core/hits_export.py on every publish. It is a separate file
 * rather than beats in each item's front matter because hits move independently of items -- a
 * threshold retune or a rebuild_hits() run changes which items are hits without changing a single
 * item, and front matter would mean rewriting 2400 files to reflect that.
 *
 * Joined on URL: the archive names files by a hash of the URL and carries the URL in front matter,
 * so neither side needs database ids.
 *
 * Only ~9.5% of archived items are hits (229 of 2423). That ratio is the whole point of this view:
 * the full archive is the raw feed, the categories are the signal.
 */
const fs = require("node:fs");
const path = require("node:path");

const items = require("./items.js");

const HITS = process.env.ARCHIVE_HITS
  || path.join(__dirname, "..", "..", "archive", "hits.json");

const DESKS = require("./desks.js");   // the one canonical list

module.exports = function () {
  let raw = [];
  try {
    raw = JSON.parse(fs.readFileSync(HITS, "utf8"));
  } catch {
    // No export yet, or an offline rebuild running without the network. A site with no categories
    // is degraded but coherent; failing the build here would make `--offline` depend on Supabase.
    raw = [];
  }

  const byUrl = new Map();
  for (const it of items()) byUrl.set(it.url, it);

  const groups = new Map();
  const perUrl = new Map();

  for (const hit of raw) {
    const item = byUrl.get(hit.url);
    if (!item) continue;              // hit on an item not in the archive tree
    const key = `${hit.newsroom}-${hit.beat}`;
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        newsroom: hit.newsroom,
        beat: hit.beat,
        name: hit.beat_name,
        items: [],
      });
    }
    groups.get(key).items.push({ ...item, score: hit.score });

    if (!perUrl.has(hit.url)) perUrl.set(hit.url, []);
    perUrl.get(hit.url).push({ key, name: hit.beat_name, newsroom: hit.newsroom, score: hit.score });
  }

  const list = [...groups.values()];
  for (const cat of list) {
    // Highest-scoring first: the ranking is the editorial signal, and a category page read top-down
    // should put the strongest match first rather than merely the newest.
    cat.items.sort((a, b) => b.score - a.score);
    cat.count = cat.items.length;
  }
  const deskRank = (id) => {
    const at = DESKS.findIndex((d) => d.id === id);
    return at === -1 ? DESKS.length : at;
  };
  list.sort((a, b) => deskRank(a.newsroom) - deskRank(b.newsroom) || b.count - a.count);

  for (const cats of perUrl.values()) cats.sort((a, b) => b.score - a.score);

  return {
    list,
    desks: DESKS.map((d) => ({
      ...d,
      categories: list.filter((c) => c.newsroom === d.id),
      count: list.filter((c) => c.newsroom === d.id).reduce((n, c) => n + c.count, 0),
    })).filter((d) => d.categories.length),
    byUrl: Object.fromEntries(perUrl),
    total: list.reduce((n, c) => n + c.count, 0),
  };
};
