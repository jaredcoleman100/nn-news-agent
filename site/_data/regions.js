/**
 * The briefs' cited stories, grouped by where the OUTLET is, for browsing by origin.
 *
 * A third browse axis, and the one that answers a question the other two cannot:
 *
 *   /topic/   what the story is ABOUT   (beat, from the embedding score)
 *   /outlet/  whose newsroom it is      (NRK or outside it -- internal build only)
 *   /region/  where the outlet SITS     (this file)
 *
 * The distinction that makes it worth having: an article about Svalbard written in Murmansk and
 * one written in Tromsø are the same topic and are not the same story. With the roster now
 * spanning four continents, "what is Asia saying about Arctic shipping" is a question the desk
 * could not previously ask, and the answer is not a subset of any beat.
 *
 * `region` is set per source in sources.json and carried through core/reports_export.py. It is
 * about the outlet, NOT the subject: a Norwegian paper reporting on China is `norway`.
 *
 * Deduplicated the same way as topics.js -- a story cited by several briefs appears once, under
 * the most recent, with every citing brief listed on its card.
 */
const reports = require("./reports.js");

// Display order is editorial, not alphabetical: nearest first, then outward. Norway leads because
// it is the largest group; Russia sits high because it is the one border that matters most to
// this desk; research and aggregators come last because they are a register, not a place.
const REGIONS = [
  { id: "norway", name: ["Norway", "Norge"] },
  { id: "nordic", name: ["Nordic neighbours", "Nordiske naboer"] },
  { id: "russia", name: ["Russia", "Russland"] },
  { id: "europe", name: ["Rest of Europe", "Resten av Europa"] },
  { id: "north-america", name: ["North America", "Nord-Amerika"] },
  // Mexico sits here rather than under North America: the grouping is by press and language, and
  // Mexican coverage of the Arctic reads with the Spanish-language hemisphere, not with Ottawa.
  { id: "latin-america", name: ["Latin America", "Latin-Amerika"] },
  { id: "asia", name: ["Asia", "Asia"] },
  { id: "middle-east", name: ["Middle East", "Midtøsten"] },
  { id: "global", name: ["International / aggregated", "Internasjonalt / aggregert"] },
  { id: "research", name: ["Research databases", "Forskningsdatabaser"] },
];

module.exports = function () {
  const briefs = reports();
  const groups = new Map();
  const seen = new Map();

  for (const r of briefs) {                 // newest brief first
    for (const s of r.stories) {
      if (!s.url) continue;
      let story = seen.get(s.url);
      if (!story) {
        story = { ...s, briefs: [], claims: [...s.claims] };
        seen.set(s.url, story);
        const key = s.region || "global";
        if (!groups.has(key)) groups.set(key, { key, stories: [] });
        groups.get(key).stories.push(story);
      } else {
        for (const claim of s.claims) {
          if (!story.claims.includes(claim)) story.claims.push(claim);
        }
      }
      story.briefs.push({ slug: r.slug, day: r.day, headline: r.headline_en || r.headline });
    }
  }

  // Declared order, and only regions that actually have stories -- an empty "Middle East" card
  // linking to an empty page is worse than no card.
  const list = REGIONS
    .filter((r) => groups.has(r.id))
    .map((r) => {
      const g = groups.get(r.id);
      return { ...r, key: r.id, stories: g.stories, count: g.stories.length };
    });

  // Anything whose region is not in the declared list still gets a page rather than vanishing.
  for (const [key, g] of groups) {
    if (!REGIONS.some((r) => r.id === key)) {
      list.push({ id: key, key, name: [key, key], stories: g.stories, count: g.stories.length });
    }
  }

  return { list, total: seen.size };
};
