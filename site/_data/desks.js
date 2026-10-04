/**
 * The newsrooms, in display order. The one canonical copy.
 *
 * This was duplicated in _data/categories.js and _data/topics.js, and a third copy was about to
 * appear in digests.njk. Worse, digests.njk was reading its desks from `categories.desks`, which
 * is derived from the ARCHIVE -- and the public build does not read the archive at all, so the
 * brief index rendered its "13 briefs" heading above an empty page. A desk is a fact about the
 * newsrooms, not about how much of their output happens to be in a given build, so it is declared
 * here rather than inferred anywhere.
 *
 * Nord-Norge first: the older desk and the larger one.
 */
module.exports = [
  { id: "nord-norge", name: ["Northern Norway", "Nord-Norge"] },
  { id: "rikspolitikk", name: ["National politics", "Rikspolitikk"] },
];
