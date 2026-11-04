/**
 * The humour products, in one canonical place.
 *
 * These desks write jokes, not news. They each have their own section (`/satire/` for the
 * politician-quote desk, `/comedy/` for the joke desk), their own disclaimer in the page
 * furniture, and their own editor gate -- and they must not appear on the news surfaces: not the
 * front page, not the brief index, not the topic pages.
 *
 * It is a list and not a hardcoded id because the single-id version already failed once.
 * index.njk excluded `satire-desk` by name (the instruction of 2026-09-28); `vitsedesken` was
 * added to the engine on 2026-11-03 and nothing excluded it. Its first run -- 39 jokes, gate
 * `blocked`, `decision: approved` only by the standing auto-approve instruction of 2026-10-08 --
 * was then the newest report of all, so it led the news front page in full, under the news nav,
 * with no humour disclaimer anywhere on the page.
 *
 * A product added here is excluded from every news surface at once. Add new humour desks to this
 * list, not to a filter in a template.
 */
module.exports = {
  products: ["satire-desk", "vitsedesken"],
};
