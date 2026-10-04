/**
 * Eleventy build for the nn-news-agent archive.
 *
 * Run it from the toolchain directory, which lives OFF the shared drive because node_modules is
 * thousands of files and would sync to everyone on it -- the same reason the venv and .env do not
 * live in the repo:
 *
 *   ARCHIVE_ITEMS="H:/.../nn-news-agent/archive/items" \
 *   ELEVENTY_OUT="C:/Users/jared/.nn-news-site/_site" \
 *   C:/Users/jared/.nn-news-site/node_modules/.bin/eleventy \
 *     --config="H:/.../nn-news-agent/site/eleventy.config.js"
 *
 * `python run.py --publish` does exactly that, then tars the output and uploads one object.
 *
 * This config requires nothing, deliberately: Node would resolve a `require` here against the
 * repo on the drive, where there is no node_modules, so any dependency would have to be reachable
 * via NODE_PATH. Keeping the config and the data layer dependency-free avoids that entirely.
 */
// The archive templates: every page that renders a source's own text, or links to one that does.
// SITE_PUBLIC=1 drops them from the build entirely rather than hiding their links, so the public
// site has no route to them and no orphaned files in the output. See site/_data/site.js.
const ARCHIVE_TEMPLATES = [
  "item.njk", "everything.njk", "browse.njk", "day.njk", "source.njk",
  "category.njk", "categories.njk", "outlet-external.njk", "outlet-own.njk",
];

module.exports = function (eleventyConfig) {
  if (process.env.SITE_PUBLIC === "1") {
    for (const t of ARCHIVE_TEMPLATES) eleventyConfig.ignores.add(t);
  }

  // Split a body on newlines into paragraphs. Item bodies are plain text extracted from articles,
  // not markdown, so rendering them as markdown would interpret stray characters as syntax.
  eleventyConfig.addFilter("paragraphs", (text) =>
    String(text || "")
      .split(/\n+/)
      .map((p) => p.trim())
      .filter(Boolean)
  );

  eleventyConfig.addFilter("slugify", (text) =>
    String(text || "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "") || "x"
  );

  // Eleventy's pagination.href.* are absolute ("/page/2/"), which breaks both targets: the offline
  // copy resolves them to the filesystem root, and the hosted site to the domain root rather than
  // /archive/. Re-anchor them to the page's own relative base.
  eleventyConfig.addFilter("rel", (url, base) =>
    (base || "./") + String(url || "").replace(/^\/+/, "")
  );

  // Nunjucks ships a `slice` filter, but it is Jinja's: it divides a list into N slices rather
  // than taking a JS-style range. These are the two operations the templates actually want.
  // Nunjucks' `selectattr(attr, "equalto", value)` does NOT compare here: it degrades to a plain
  // truthiness test on the attribute and ignores the operand. That is silent and it lies -- the
  // satire page reported "13 drafted and waiting" when three of the thirteen briefs are satire,
  // and the digests page listed every brief under every desk. Use this instead.
  eleventyConfig.addFilter("where", (list, key, value) =>
    (list || []).filter((x) => x && x[key] === value));

  eleventyConfig.addFilter("without", (list, key, value) =>
    (list || []).filter((x) => x && x[key] !== value));

  // Thousands separators. "9230" on a page about scale reads as a typo.
  eleventyConfig.addFilter("num", (n) => Number(n || 0).toLocaleString("en-GB"));

  // Markdown for bodies the desks write as markdown. `| safe` at the call site is correct:
  // _data/markdown.js escapes every line BEFORE adding any tag, so the only HTML that
  // reaches the page is what it produced.
  const md = require("./_data/markdown.js");
  eleventyConfig.addFilter("markdown", (text) => md.render(text));

  // "Kongen i norsk litteratur 2: Kongen under Gud og loven" -> "Kongen under Gud og loven".
  // The series prefix is on every chapter title; beside a chapter number it is noise.
  eleventyConfig.addFilter("after_colon", (t) => {
    const s = String(t || "");
    const at = s.indexOf(": ");
    return at === -1 ? s : s.slice(at + 2);
  });

  eleventyConfig.addFilter("take", (list, n) => (list || []).slice(0, n));
  eleventyConfig.addFilter("drop", (list, n) => (list || []).slice(n));

  // First n characters, with no ellipsis -- for trimming an ISO timestamp to minutes.
  eleventyConfig.addFilter("clip", (text, n) => String(text || "").slice(0, n));

  eleventyConfig.addFilter("truncate", (text, n) => {
    const s = String(text || "");
    if (s.length <= n) return s;
    const cut = s.slice(0, n);
    const at = cut.lastIndexOf(" ");
    return (at > n * 0.6 ? cut.slice(0, at) : cut) + "…";
  });

  // Read the archive once, here, rather than digging the global data out of collectionApi --
  // getAll()[0].data.items depends on at least one template already existing and on Eleventy's
  // internal ordering, which is a fragile way to reach data this config owns outright.
  // Not in the public build: every collection below feeds an archive template, all of which are
  // ignored above, and the walk is the slowest thing in the build.
  const allItems = process.env.SITE_PUBLIC === "1" ? [] : require("./_data/items.js")();

  eleventyConfig.addCollection("external", () => allItems.filter((i) => i.org === "external"));
  eleventyConfig.addCollection("own", () => allItems.filter((i) => i.org === "own"));

  // Distinct sources, each with its item count, for the browse page and the source pages.
  eleventyConfig.addCollection("sources", () => {
    const items = allItems;
    const by = new Map();
    for (const item of items) {
      if (!by.has(item.source)) by.set(item.source, { name: item.source, org: item.org, items: [] });
      by.get(item.source).items.push(item);
    }
    return [...by.values()].sort((a, b) => b.items.length - a.items.length);
  });

  eleventyConfig.addCollection("days", () => {
    const items = allItems;
    const by = new Map();
    for (const item of items) {
      if (!by.has(item.day)) by.set(item.day, { day: item.day, items: [] });
      by.get(item.day).items.push(item);
    }
    return [...by.values()].sort((a, b) => b.day.localeCompare(a.day));
  });

  return {
    dir: {
      input: ".",
      includes: "_includes",
      data: "_data",
      output: process.env.ELEVENTY_OUT || "_site",
    },
    // Relative, so the site works served from any prefix -- it sits under /archive/ on the Fly
    // worker, not at a domain root.
    pathPrefix: "/",
    markdownTemplateEngine: "njk",
    htmlTemplateEngine: "njk",
  };
};
