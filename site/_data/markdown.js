/**
 * A small markdown renderer, for bodies the desks write as markdown.
 *
 * WHY THIS EXISTS AND WHY IT IS NOT A LIBRARY
 * The norlit pieces and the briefs are markdown: headings, blockquotes, lists, emphasis. Until now
 * the templates ran them through a `paragraphs` filter that only split on blank lines, so the
 * Ibsen pastiche published its disclaimer as literal asterisks -- «*This is an imagined text*» --
 * which is exactly the sentence that most needed to read as a disclaimer rather than as syntax.
 *
 * It is hand-rolled because site/eleventy.config.js is deliberately dependency-free: Node resolves
 * a `require` there against the shared Google Drive, where there is no node_modules, so a markdown
 * library would have to live on NODE_PATH. See that file's header.
 *
 * SAFETY: every line is HTML-escaped BEFORE any markup is introduced. The only tags that reach the
 * page are the ones produced here. Order matters -- escape first, then add tags, never the reverse,
 * or a quotation containing an angle bracket closes a tag the renderer opened.
 */

const esc = (t) => String(t == null ? "" : t)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** Inline: bold, italic, inline code, and links. Applied to already-escaped text. */
function inline(t) {
  return t
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    // Single * or _ for italic, but not inside a word (snake_case survives intact).
    .replace(/(^|[\s(（])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/(^|[\s(（])_([^_\n]+)_/g, "$1<em>$2</em>")
    // Links: the href is escaped text, and only http(s) is allowed through.
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
             '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

function render(src) {
  const lines = String(src || "").replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let para = [];
  let list = null;          // "ul" | "ol" | null
  let quote = [];

  const flushPara = () => {
    if (para.length) { out.push(`<p>${inline(para.join(" "))}</p>`); para = []; }
  };
  const flushList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  const flushQuote = () => {
    if (quote.length) {
      out.push(`<blockquote>${quote.map((q) => `<p>${inline(q)}</p>`).join("")}</blockquote>`);
      quote = [];
    }
  };
  const flushAll = () => { flushPara(); flushList(); flushQuote(); };

  for (const raw of lines) {
    const line = esc(raw).trim();

    if (!line) { flushAll(); continue; }

    // Horizontal rule. Checked before emphasis so --- is not read as an em dash run.
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(line)) { flushAll(); out.push("<hr>"); continue; }

    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      flushAll();
      // Shifted down two: the page already owns h1 (the masthead) and h2 (section headings), so a
      // body's `#` must not compete with them in the document outline.
      const level = Math.min(h[1].length + 2, 6);
      out.push(`<h${level}>${inline(h[2])}</h${level}>`);
      continue;
    }

    const q = /^>\s?(.*)$/.exec(line);
    if (q) { flushPara(); flushList(); quote.push(q[1]); continue; }
    flushQuote();

    const ul = /^[-*•]\s+(.*)$/.exec(line);
    const ol = /^\d+[.)]\s+(.*)$/.exec(line);
    if (ul || ol) {
      flushPara();
      const want = ul ? "ul" : "ol";
      if (list !== want) { flushList(); out.push(`<${want}>`); list = want; }
      out.push(`<li>${inline((ul || ol)[1])}</li>`);
      continue;
    }
    flushList();

    para.push(line);
  }
  flushAll();
  return out.join("\n");
}

module.exports = { render };
