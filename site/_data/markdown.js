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

function anchor(href, text) {
  return `<a href="${href}" target="_blank" rel="noopener noreferrer">${text}</a>`;
}

/** What a bare URL should READ as. Short ones stay whole; long ones become host + ellipsis. */
function shorten(href) {
  if (href.length <= 60) return href;
  return `${href.replace(/^https?:\/\//, "").split("/")[0]}/…`;
}

/**
 * Inline formatting, applied to already-escaped text.
 *
 * THIS IS THE ONE INLINE RENDERER. The Norlit pieces and the briefs both go through it.
 *
 * There used to be two. This file handled links; _data/reports.js had its own copy that handled
 * only **bold**, because when it was written the brief templates forbade URLs in the body. The
 * briefs stopped obeying that, and 605 markdown links published as literal text -- four hundred
 * characters of Google News redirect, mid-sentence, on a public indexed site. Nothing made the two
 * agree, so they drifted silently and the drift was invisible until someone read the page. Merged
 * 2026-10-07; reports.js now calls inlineText() here and owns only its block structure.
 *
 * ORDER MATTERS, twice over:
 *   - Escaping happens before any of this (see esc), or a source's angle bracket closes a tag.
 *   - Links are parked behind placeholders BEFORE emphasis runs and restored after, because a URL
 *     may contain _ or * and the emphasis rules would otherwise eat into the href. Parking also
 *     stops the bare-URL pass from re-linking a href the markdown-link pass just wrote.
 *
 * Only http(s) is linked, so a `javascript:` URL stays inert text.
 */
function inline(t) {
  const parked = [];
  const park = (html) => `\u0000${parked.push(html) - 1}\u0000`;

  let s = t
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]\n]+)\]\((https?:\/\/[^)\s"'<>]+)\)/g,
             (_m, text, href) => park(anchor(href, text)))
    // Bare URLs written straight into prose. The satire desk cites hoyre.no that way and the world
    // brief does it with Google News redirects, so the label is shortened and the href kept whole.
    .replace(/(^|[\s(（])(https?:\/\/[^\s<>"'）)]+)/g,
             (_m, lead, href) => lead + park(anchor(href, shorten(href))));

  s = s
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    // Single * or _ for italic, but not inside a word (snake_case survives intact).
    .replace(/(^|[\s(（])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/(^|[\s(（])_([^_\n]+)_/g, "$1<em>$2</em>");

  return s.replace(/\u0000(\d+)\u0000/g, (_m, i) => parked[Number(i)]);
}

/** Escape raw text and format it, for callers holding raw markdown rather than escaped text. */
function inlineText(raw) {
  return inline(esc(raw));
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

module.exports = { render, inline, inlineText, esc };
