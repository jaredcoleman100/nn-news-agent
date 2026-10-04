/**
 * Measured facts about the desk, for the explainer page.
 *
 * Written by core/reports_export.py's export_pipeline() on every build. Nothing on that page is
 * typed by hand: a page that describes a monitoring system is worthless the moment its numbers are
 * stale, and they go stale in days. An empty object is a safe fallback -- the template omits the
 * figures rather than printing zeroes it cannot stand behind.
 */
const fs = require("node:fs");
const path = require("node:path");

const FILE = process.env.ARCHIVE_PIPELINE
  || path.join(__dirname, "..", "..", "archive", "pipeline.json");

module.exports = function () {
  try {
    return JSON.parse(fs.readFileSync(FILE, "utf8"));
  } catch {
    return { languages: [], outlets: [] };
  }
};
