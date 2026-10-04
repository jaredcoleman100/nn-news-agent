/**
 * The site's access gate. Copied to `_worker.js` in the published directory by core/publish.py.
 *
 * WHY A COOKIE AND NOT CLOUDFLARE ACCESS
 * Access is the better control -- per-person identity, an audit trail, revocation. It needs Zero
 * Trust enabled on the account and an API token with Access-edit scope, and this machine's token
 * carries `zone (read)` only. It also needs the reviewer's email address, which nobody has given
 * me. So this: one shared key, exchanged once for a cookie. Weaker, and honest about it -- a
 * leaked link is a leaked key, and it cannot tell one reader from another.
 *
 * Replace it with Access when the scope and the address exist; the only change here is deleting
 * this file and removing the copy step.
 *
 * HOW IT BEHAVES
 *   ?k=<SITE_KEY>  -> sets an HttpOnly cookie and 303s to the bare path, so the key does not stay
 *                     in the address bar, in history, in a bookmark or in a referrer header.
 *   cookie present -> the site, served normally from ASSETS.
 *   neither        -> a short page explaining there is a key, HTTP 401.
 *
 * IT FAILS CLOSED. With SITE_KEY unset the whole site returns 503 rather than serving. That is
 * deliberate: a gate that opens when its configuration goes missing is not a gate. It also means
 * the secret must be set BEFORE this is first deployed, or the site goes dark in between.
 */

const COOKIE = "nrn_site";

const enc = new TextEncoder();

function timingSafeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function sessionValue(key) {
  const buf = await crypto.subtle.digest("SHA-256", enc.encode(`nrn-site|v1|${key}`));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function cookies(request) {
  const out = {};
  for (const part of (request.headers.get("cookie") || "").split(";")) {
    const at = part.indexOf("=");
    if (at > 0) out[part.slice(0, at).trim()] = part.slice(at + 1).trim();
  }
  return out;
}

const PAGE = (title, body, status) => new Response(
  `<!doctype html><html lang="nb"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>${title}</title>
<style>
:root{--bg:#fbfaf8;--ink:#1a1c1e;--muted:#6a7075;--accent:#ba0c2f;--gold:#a8842c;--line:#e4e2dd}
@media(prefers-color-scheme:dark){:root{--bg:#16181a;--ink:#e8e6e3;--muted:#9aa0a6;--accent:#e8647c;--gold:#d8b45c;--line:#2e3237}}
body{background:var(--bg);color:var(--ink);margin:0;min-height:100vh;display:grid;place-items:center;
     padding:24px;font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.box{max-width:30rem;text-align:center}
h1{font-family:Georgia,serif;font-size:1.6rem;margin:0 0 4px;letter-spacing:.01em}
.motto{font-style:italic;color:var(--muted);font-size:.92rem;margin:0 0 22px}
.rule{border-top:2px solid var(--gold);border-bottom:1px solid var(--accent);height:3px;margin:0 0 20px}
p{color:var(--muted);font-size:.95rem}
</style></head><body><div class="box">
<h1>Royal News of Norway</h1><p class="motto">News fit for a queen</p><div class="rule"></div>
${body}</div></body></html>`,
  { status, headers: { "content-type": "text/html; charset=utf-8",
                       "cache-control": "no-store",
                       "x-robots-tag": "noindex, nofollow" } });

export default {
  async fetch(request, env) {
    if (!env.SITE_KEY) {
      return PAGE("Not configured",
        "<p>This site is gated and its key is not configured. Nothing is being served.</p>", 503);
    }

    const url = new URL(request.url);
    const k = url.searchParams.get("k");
    if (k && timingSafeEqual(k, env.SITE_KEY)) {
      return new Response(null, {
        status: 303,
        headers: {
          location: url.origin + url.pathname,
          "cache-control": "no-store",
          // 30 days, HttpOnly so no script can read it, SameSite=Lax so it survives a normal
          // click-through from mail without riding along on cross-site requests.
          "set-cookie": `${COOKIE}=${await sessionValue(env.SITE_KEY)}; HttpOnly; Secure; `
                        + "SameSite=Lax; Path=/; Max-Age=2592000",
        },
      });
    }

    const got = cookies(request)[COOKIE] || "";
    if (got && timingSafeEqual(got, await sessionValue(env.SITE_KEY))) {
      return env.ASSETS.fetch(request);
    }

    return PAGE("Not public yet",
      "<p>This edition is in review and is not public. Open it with the link you were sent; "
      + "it will remember you on this browser for a month.</p>"
      + "<p lang=\"nb\">Denne utgaven er til gjennomsyn og er ikke offentlig. "
      + "Åpne den med lenken du fikk tilsendt; den husker deg i denne nettleseren i en måned.</p>",
      401);
  },
};
