/**
 * nn-news-agent — the editor's review queue, as a Cloudflare Worker.
 *
 * WHY THIS AND NOT THE APPS SCRIPT
 * The Apps Script version was written when the choice was between Supabase Edge Functions, which
 * wrap every response in `Content-Security-Policy: default-src 'none'; sandbox` with
 * `Content-Type: text/plain` so a browser shows source instead of a page, and the Fly worker,
 * whose trial had lapsed. Apps Script served real HTML, cost nothing and used the editor's
 * existing Google session.
 *
 * Both constraints are gone. Cloudflare now hosts the brief site, serves real HTML with no
 * sandbox, and is not on a trial. The decisive difference is deployment: an Apps Script can only
 * be updated by pasting code into a browser, which is why that file sat undeployed with `app_log`
 * empty. This deploys with the same `wrangler` that ships the site.
 *
 * WHAT IT IS FOR
 * `reports.editor_decision` had never been written to, because there was nowhere for a human to
 * act. Approving here is what releases a held brief.
 *
 * SECRETS
 *   REVIEW_SECRET   shared secret for the Supabase function. NOT a Supabase key -- the function
 *                   holds the service-role key and this Worker never sees it.
 *   REVIEW_KEY      the one-time key for the cookie fallback below. Unused once Access is on.
 * Set both with:  wrangler secret put <NAME>
 */

const COOKIE = "nrn_review";

// ---------------------------------------------------------------- auth
//
// TWO WAYS IN, and the Worker is never open on either path.
//
// 1. Cloudflare Access (preferred). Set ACCESS_TEAM and ACCESS_AUD and every request must carry a
//    valid, unexpired Access JWT signed by your team's keys, with the audience of this specific
//    application. This is verified HERE rather than trusted from the edge on purpose: an Access
//    application is bound to a hostname, and this Worker also answers on its workers.dev URL,
//    which such a policy does not cover. Checking the assertion in the Worker closes that bypass.
//
// 2. A cookie session (fallback, for before Access exists -- configuring it needs a Cloudflare
//    zone and a Zero Trust scope this machine's token does not have). Visiting the URL once with
//    `?k=<REVIEW_KEY>` sets an HttpOnly cookie and redirects to strip the key from the address
//    bar, so the secret does not stay in history, bookmarks or referrers. The cookie holds a hash
//    of the key, not the key. It is a weaker control than Access and is meant to be replaced.

const enc = new TextEncoder();

function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function sha256Hex(text) {
  const buf = await crypto.subtle.digest("SHA-256", enc.encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** The cookie value for a given key. A hash, so the cookie never carries the key itself. */
const sessionValue = (key) => sha256Hex(`nrn-review-session|v1|${key}`);

function cookies(req) {
  const out = {};
  for (const part of (req.headers.get("cookie") || "").split(";")) {
    const at = part.indexOf("=");
    if (at > 0) out[part.slice(0, at).trim()] = part.slice(at + 1).trim();
  }
  return out;
}

const b64urlToBytes = (s) =>
  Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/")
    .padEnd(s.length + ((4 - (s.length % 4)) % 4), "=")), (c) => c.charCodeAt(0));

let jwksCache = { at: 0, keys: null };

async function accessKeys(team) {
  // Ten minutes: long enough that a burst of decisions is one fetch, short enough that a key
  // rotation takes effect without a redeploy.
  if (jwksCache.keys && Date.now() - jwksCache.at < 600_000) return jwksCache.keys;
  const res = await fetch(`https://${team}.cloudflareaccess.com/cdn-cgi/access/certs`);
  if (!res.ok) throw new Error(`Access certs ${res.status}`);
  const { keys } = await res.json();
  jwksCache = { at: Date.now(), keys };
  return keys;
}

async function verifyAccessJwt(token, team, aud) {
  const [h, p, s] = String(token || "").split(".");
  if (!h || !p || !s) return null;
  const header = JSON.parse(new TextDecoder().decode(b64urlToBytes(h)));
  if (header.alg !== "RS256") return null;            // only what Access actually issues

  const jwk = (await accessKeys(team)).find((k) => k.kid === header.kid);
  if (!jwk) return null;

  const key = await crypto.subtle.importKey(
    "jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
  const ok = await crypto.subtle.verify(
    "RSASSA-PKCS1-v1_5", key, b64urlToBytes(s), enc.encode(`${h}.${p}`));
  if (!ok) return null;

  const claims = JSON.parse(new TextDecoder().decode(b64urlToBytes(p)));
  const now = Math.floor(Date.now() / 1000);
  if (claims.exp && claims.exp < now) return null;
  if (claims.nbf && claims.nbf > now) return null;
  // `aud` is an array. Without this check any Access application on the account would open this
  // one, which is the mistake that makes Access look like it is working when it is not.
  const auds = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
  if (!auds.includes(aud)) return null;
  if (claims.iss && claims.iss !== `https://${team}.cloudflareaccess.com`) return null;
  return claims;
}

/** @returns {Promise<{ok: true, who: string} | {ok: false, why: string}>} */
async function authorise(req, env) {
  const team = (env.ACCESS_TEAM || "").trim();
  const aud = (env.ACCESS_AUD || "").trim();

  if (team && aud) {
    const token = req.headers.get("cf-access-jwt-assertion")
      || cookies(req).CF_Authorization;
    if (!token) return { ok: false, why: "no Access assertion on this request" };
    const claims = await verifyAccessJwt(token, team, aud);
    if (!claims) return { ok: false, why: "Access assertion did not verify" };
    return { ok: true, who: claims.email || claims.sub || "access" };
  }

  if (!env.REVIEW_KEY) {
    // Fail closed. A Worker with neither Access configured nor a key set must not be readable:
    // it renders unpublished drafts and can kill them.
    return { ok: false, why: "not configured: set REVIEW_KEY, or ACCESS_TEAM + ACCESS_AUD" };
  }
  const want = await sessionValue(env.REVIEW_KEY);
  const got = cookies(req)[COOKIE] || "";
  if (got && timingSafeEqual(got, want)) return { ok: true, who: "cookie session" };
  return { ok: false, why: "no session" };
}

// ---------------------------------------------------------------- supabase

async function api(env, payload) {
  const res = await fetch(env.REVIEW_API, {
    method: "POST",
    headers: { "content-type": "application/json", "x-review-secret": env.REVIEW_SECRET },
    body: JSON.stringify(payload),
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`review API ${res.status}: ${text.slice(0, 300)}`);
  return JSON.parse(text);
}

// ---------------------------------------------------------------- rendering

const esc = (s) => String(s ?? "")
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const CSS = `
:root{--bg:#fbfaf8;--panel:#fff;--ink:#1a1c1e;--muted:#6a7075;--line:#e4e2dd;--accent:#7a1f1f;--chip:#f0eee9;--ok:#1f5c3a}
@media(prefers-color-scheme:dark){:root{--bg:#16181a;--panel:#1e2124;--ink:#e8e6e3;--muted:#9aa0a6;--line:#2e3237;--accent:#e08a8a;--chip:#262a2e;--ok:#7fd1a5}}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);margin:0 auto;max-width:1000px;padding:26px 18px;
     font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
h1{font-size:1.4rem;margin:0 0 2px}h1 .alt{display:block;font-size:.9rem;font-weight:500;color:var(--muted)}
.sub{color:var(--muted);font-size:.85rem;margin:0 0 20px}.sub .alt{display:block}
.err{background:var(--accent);color:var(--bg);padding:11px 14px;border-radius:8px;margin-bottom:18px;font-size:.88rem}
.rep{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin-bottom:18px}
.rep h2{font-size:1.05rem;margin:0 0 6px;line-height:1.35}
.meta{font-size:.78rem;color:var(--muted);display:flex;flex-wrap:wrap;gap:7px;align-items:center;margin-bottom:11px}
.chip{background:var(--chip);border-radius:20px;padding:2px 9px;font-size:.74rem}
.chip.blocked{background:var(--accent);color:var(--bg)}
.flag{font-size:.82rem;border-left:3px solid var(--accent);padding:3px 0 3px 10px;margin:5px 0}
.flag b{font-weight:600}.flag .ev{color:var(--muted)}
details{margin:11px 0;border-top:1px solid var(--line);padding-top:9px}
summary{cursor:pointer;font-size:.85rem;color:var(--muted);font-weight:600}
.body{white-space:pre-wrap;font-size:.92rem;margin:9px 0 0}
.claim{border-top:1px solid var(--line);padding:9px 0;font-size:.89rem}
.claim .t{margin:0 0 3px}.claim .en{color:var(--muted);font-size:.84rem;margin:0 0 4px}
.claim a{font-size:.8rem}
form.act{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:13px;padding-top:12px;border-top:1px solid var(--line)}
input[type=text]{flex:1 1 260px;font:inherit;padding:7px 10px;border:1px solid var(--line);border-radius:7px;background:var(--bg);color:var(--ink)}
button{font:inherit;padding:7px 14px;border-radius:7px;border:1px solid var(--line);background:var(--chip);color:var(--ink);cursor:pointer}
button.ok{background:var(--ok);color:var(--bg);border-color:transparent}
button.no{background:var(--accent);color:var(--bg);border-color:transparent}
.empty{color:var(--muted);text-align:center;padding:40px 0}
.note{font-size:.8rem;color:var(--muted);margin-top:26px;border-top:1px solid var(--line);padding-top:12px}
`;

const page = (body, status = 200) => new Response(
  `<!doctype html><html lang="nb"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer">
<title>Review queue / Redaksjonskø</title><style>${CSS}</style></head><body>
<h1>Review queue<span class="alt">Redaksjonskø</span></h1>${body}</body></html>`,
  { status, headers: { "content-type": "text/html; charset=utf-8",
                       "x-robots-tag": "noindex, nofollow",
                       "cache-control": "no-store" } });

function renderReport(r) {
  const flags = (r.flags || []).length
    ? r.flags.map((f) => `<div class="flag"><b>${esc(f.flag)}</b> · ${esc(f.severity)}
        <span class="ev">${esc((f.clauses || []).join(", "))}${
          (f.evidence || []).length ? " — «" + esc(f.evidence.join("», «")) + "»" : ""}</span></div>`).join("")
    : '<div class="flag"><b>no flags above note</b></div>';

  const claims = (r.claims || []).map((c) => `<div class="claim">
      <p class="t">${esc(c.claim)}</p>
      ${c.title_en ? `<p class="en">${esc(c.title_en)}</p>` : ""}
      ${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener noreferrer">original →</a>` : ""}
    </div>`).join("");

  return `<div class="rep">
    <h2>${esc(r.headline)}</h2>
    <div class="meta">
      <span class="chip${r.gate === "blocked" ? " blocked" : ""}">${esc(r.gate)}</span>
      <span class="chip">${esc(r.newsroom)}</span><span>${esc(r.product)}</span>
      <span>${esc(String(r.created_at).slice(0, 16).replace("T", " "))}</span>
    </div>
    ${flags}
    <details open><summary>Digest · Bokmål</summary><div class="body">${esc(r.body)}</div></details>
    ${r.body_en ? `<details><summary>English</summary><div class="body">${esc(r.body_en)}</div></details>` : ""}
    <details><summary>${(r.claims || []).length} claims, with sources</summary>${claims}</details>
    <form class="act" method="POST">
      <input type="hidden" name="id" value="${esc(r.id)}">
      <input type="text" name="reason" placeholder="Reason (optional) / Begrunnelse" autocomplete="off">
      <button class="ok" name="decision" value="approved">Approve &amp; send</button>
      <button name="decision" value="revise">Needs revision</button>
      <button class="no" name="decision" value="killed">Kill</button>
    </form>
  </div>`;
}

// ---------------------------------------------------------------- handler

export default {
  async fetch(req, env) {
    const url = new URL(req.url);

    // The one-time key link: set the cookie, then 303 to the bare path so the key leaves the
    // address bar before anything is rendered. Bookmark the clean URL, not this one.
    const k = url.searchParams.get("k");
    if (k && env.REVIEW_KEY && timingSafeEqual(k, env.REVIEW_KEY)) {
      const value = await sessionValue(env.REVIEW_KEY);
      return new Response(null, {
        status: 303,
        headers: {
          location: url.origin + url.pathname,
          "set-cookie": `${COOKIE}=${value}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=2592000`,
        },
      });
    }

    const auth = await authorise(req, env);
    if (!auth.ok) {
      return page(`<div class="err">Not authorised — ${esc(auth.why)}.</div>
        <p class="note">This page shows unpublished drafts and can kill them, so it does not open
        without one of: a verified Cloudflare Access assertion, or a session started once from the
        key link. Nothing is logged about this attempt beyond Cloudflare's own request log.</p>`, 403);
    }

    if (req.method === "POST") {
      const form = await req.formData();
      const id = Number(form.get("id"));
      const decision = String(form.get("decision") || "");
      const reason = String(form.get("reason") || "").slice(0, 2000);
      if (!id || !["approved", "revise", "killed"].includes(decision)) {
        return page('<div class="err">Bad request.</div>', 400);
      }
      try {
        await api(env, { action: "decide", id, decision, reason });
        await api(env, {
          action: "log", level: "info", message: "decision recorded",
          source: "cloudflare-worker",
          context: { id, decision, by: auth.who },
        });
      } catch (e) {
        return page(`<div class="err">${esc(e.message)}</div>`, 502);
      }
      // 303 so a refresh cannot re-submit the decision.
      return new Response(null, { status: 303, headers: { location: url.origin + url.pathname } });
    }

    let data;
    try {
      data = await api(env, { action: "list" });
    } catch (e) {
      return page(`<div class="err">${esc(e.message)}</div>`, 502);
    }

    const reports = data.reports || [];
    if (!reports.length) {
      return page(`<p class="empty">Nothing awaiting a decision.<br>Ingenting venter på avgjørelse.</p>
        <p class="note">${data.decided || 0} decided so far. Signed in as ${esc(auth.who)}.</p>`);
    }
    return page(`<p class="sub">${reports.length} awaiting a decision · ${data.decided || 0} decided
      <span class="alt">Godkjenning sender rapporten ved neste tømming av utboksen (hvert 5. minutt).</span></p>
      ${reports.map(renderReport).join("")}
      <p class="note">Signed in as ${esc(auth.who)}.</p>`);
  },
};
