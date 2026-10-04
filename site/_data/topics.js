/**
 * The briefs' cited stories, grouped by category, for browsing.
 *
 * NOT the same thing as _data/categories.js, and the difference matters:
 *
 *   categories.js  every scored hit in the archive, joined to the archived item. 229 hits, and a
 *                  category page shows the source's own text. Internal build only.
 *   topics.js      only the stories a brief actually cited, carrying our claim about each and a
 *                  link out. 109 stories. Safe to publish, because it contains no source text.
 *
 * They share a key shape (`<newsroom>-<beat>`, built identically in core/reports_export.py) so a
 * category means the same thing on both surfaces, and they live at different URLs -- /category/
 * and /topic/ -- so one build can carry both without a collision.
 *
 * A story cited by two briefs appears once, under the brief that cited it first, with every brief
 * that used it listed on the card. Otherwise a recurring story -- the FOT-rutene airport cuts ran
 * in four briefs -- would fill its category with near-identical copies of itself.
 */
const reports = require("./reports.js");

const DESKS = require("./desks.js");   // the one canonical list

module.exports = function () {
  const briefs = reports();
  const groups = new Map();
  const seen = new Map();          // url -> the story object already placed

  // Newest brief first, so "first cited" means the most recent framing of a recurring story.
  for (const r of briefs) {
    for (const s of r.stories) {
      if (!s.url) continue;
      let story = seen.get(s.url);
      if (!story) {
        story = { ...s, briefs: [], claims: [...s.claims] };
        seen.set(s.url, story);
        for (const c of s.cats) {
          if (!groups.has(c.key)) {
            groups.set(c.key, {
              key: c.key,
              name: c.name,
              newsroom: c.newsroom,
              stories: [],
            });
          }
          groups.get(c.key).stories.push({ story, score: c.score });
        }
      } else {
        // Same article, cited again. Keep the claims that are new -- a later brief often makes a
        // different point about the same piece.
        for (const claim of s.claims) {
          if (!story.claims.includes(claim)) story.claims.push(claim);
        }
      }
      story.briefs.push({ slug: r.slug, day: r.day, headline: r.headline_en || r.headline });
    }
  }

  const list = [...groups.values()];
  for (const g of list) {
    // Strongest match first: the score is the editorial signal, same ordering category.njk uses.
    g.stories.sort((a, b) => b.score - a.score);
    g.stories = g.stories.map((x) => x.story);
    g.count = g.stories.length;
  }

  const deskRank = (id) => {
    const at = DESKS.findIndex((d) => d.id === id);
    return at === -1 ? DESKS.length : at;
  };
  list.sort((a, b) => deskRank(a.newsroom) - deskRank(b.newsroom) || b.count - a.count);

  return {
    list,
    desks: DESKS.map((d) => ({
      ...d,
      categories: list.filter((c) => c.newsroom === d.id),
      count: list.filter((c) => c.newsroom === d.id).reduce((n, c) => n + c.count, 0),
    })).filter((d) => d.categories.length),
    // Distinct stories, not the sum of category counts: a story in two categories is one story.
    total: seen.size,
    uncategorised: [...seen.values()].filter((s) => !s.cats.length).length,
  };
};
