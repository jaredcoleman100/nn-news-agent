/**
 * Entity pictures from Wikimedia Commons, written by core/images.py.
 *
 * Keyed by entity name. Each record carries everything the licence requires to be shown next to
 * the image: artist, licence name, a link to the licence, and a link to the Commons file page.
 * core/images.py refuses anything it cannot prove is free, so a missing entry means "no picture",
 * never "picture without attribution".
 */
const fs = require("node:fs");
const path = require("node:path");
const FILE = process.env.ARCHIVE_IMAGES
  || path.join(__dirname, "..", "..", "archive", "images.json");
module.exports = function () {
  try {
    return JSON.parse(fs.readFileSync(FILE, "utf8"));
  } catch {
    return {};
  }
};
