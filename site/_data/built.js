/**
 * When this build ran, in Oslo time, and how long ago the newest brief is.
 *
 * WHY THE PAGE SAYS THIS OUT LOUD
 * The site is published by a scheduled task on one laptop. On 2026-10-03 that task did not run --
 * the machine was asleep -- and the site went on serving the 2 October brief with nothing on it
 * saying the day had been missed. A stale page that looks current is the worst failure this thing
 * has, because it is the one nobody notices. So every page carries its own build time, and when
 * the newest brief is not from today the page says that too, in both languages.
 *
 * Dependency-free on purpose: see the header of site/eleventy.config.js.
 */
const OSLO = "Europe/Oslo";

function osloParts(d) {
  // en-CA gives YYYY-MM-DD, which sorts and compares as a date string without a Date round-trip.
  const day = d.toLocaleDateString("en-CA", { timeZone: OSLO });
  const time = d.toLocaleTimeString("en-GB", { timeZone: OSLO, hour: "2-digit", minute: "2-digit" });
  return { day, time };
}

module.exports = () => {
  const now = new Date();
  const { day, time } = osloParts(now);

  // The newest brief's day, read from the same export the pages render from.
  let newest = null;
  try {
    const reports = require("./reports.js")();
    for (const r of reports) if (!newest || (r.day || "") > newest) newest = r.day || null;
  } catch (e) {
    newest = null;
  }

  let staleDays = null;
  if (newest) {
    const ms = Date.parse(day + "T00:00:00Z") - Date.parse(newest + "T00:00:00Z");
    staleDays = Math.max(0, Math.round(ms / 86400000));
  }
  return { day, time, newest, staleDays, stale: staleDays !== null && staleDays >= 1 };
};
