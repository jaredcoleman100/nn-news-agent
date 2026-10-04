// Edge Function: JSON API behind the review page.
//
// It serves DATA, not HTML, and that is not a style choice. Supabase wraps every Edge Function
// response in `Content-Security-Policy: default-src 'none'; sandbox` with `Content-Type:
// text/plain` and `X-Content-Type-Options: nosniff`, whatever headers the function sets -- the
// same anti-XSS policy that makes signed Storage URLs unable to render a page. A browser shows
// source instead of a page. JSON is unaffected, so the page lives elsewhere and this feeds it.
//
// THE CLIENT IS `worker-review/`, A CLOUDFLARE WORKER (2026-09-28).
// It was a Google Apps Script web app, chosen when the only alternatives were this function
// (sandboxed) and the Fly worker (trial lapsed). Both constraints are gone: Cloudflare now hosts
// the brief site, serves real HTML, and deploys from the command line -- which matters, because
// an Apps Script can only be updated by pasting code into a browser, and that is why the script
// sat undeployed with `app_log` empty for a day. This function did not change when the client
// did; only its comments and the `log` action's default source did.
//
// Why the gate needed a surface at all: until now `blocked`, `review` and `clear` all delivered
// identically -- pipeline.py only uses the gate to trigger a revision and both products set
// max_revisions to 0 -- so the only difference was a "[BLOCKED]" subject prefix that every digest
// carried, for vocabulary like "elever" and "kritiserer". `reports.editor_decision` existed from
// the start and had never once been written to.
//
// Actions (POST JSON, header x-review-secret: config.review_api_secret):
//   {action:"list"}                              -> pending reports, flags, claims + translations
//   {action:"decide", id, decision, reason}      -> record; "approved" also releases the held email
//   {action:"log", level, message, context, source?}
//                                                -> append to app_log, so the client's behaviour is
//                                                   inspectable with SQL from anywhere
import { createClient } from "npm:@supabase/supabase-js@2";

const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

async function secretOk(req: Request): Promise<boolean> {
  const { data } = await sb.from("config").select("value").eq("key", "review_api_secret").maybeSingle();
  const want = String(data?.value ?? "");
  const got = req.headers.get("x-review-secret") ?? "";
  if (!want || got.length !== want.length) return false;
  let diff = 0;                                   // constant time; length already matched
  for (let i = 0; i < got.length; i++) diff |= got.charCodeAt(i) ^ want.charCodeAt(i);
  return diff === 0;
}

async function note(level: string, message: string, context: unknown = {}, source = "review-fn") {
  await sb.from("app_log").insert({ source, level, message, context });
}

async function list() {
  const { data: reports, error } = await sb.from("reports")
    .select("id,newsroom_id,product_id,gate,headline,body,sections,claims,screen_result,created_at")
    .is("editor_decision", null).order("created_at", { ascending: false }).limit(20);
  if (error) throw new Error(`list reports: ${error.message}`);

  const { count: decided } = await sb.from("reports")
    .select("id", { count: "exact", head: true }).not("editor_decision", "is", null);

  // Every claim's source_url in one lookup, so each claim can show its English title beside the
  // original link. The archive is bilingual; this is where that pays off.
  const urls = [...new Set((reports ?? []).flatMap((r) =>
    (r.claims ?? []).map((c: Record<string, string>) => c?.source_url).filter(Boolean)))];
  const items = new Map<string, Record<string, unknown>>();
  for (let i = 0; i < urls.length; i += 100) {
    const { data } = await sb.from("items").select("url,title,title_en,lang")
      .in("url", urls.slice(i, i + 100));
    for (const it of data ?? []) items.set(it.url as string, it);
  }

  return {
    decided: decided ?? 0,
    reports: (reports ?? []).map((r) => ({
      id: r.id,
      newsroom: r.newsroom_id,
      product: r.product_id,
      gate: r.gate,
      headline: r.headline,
      body: r.body,
      body_en: r.sections?.body_en ?? "",
      created_at: r.created_at,
      flags: (r.screen_result?.ethics?.flags ?? [])
        .filter((f: Record<string, unknown>) => f.severity !== "note")
        .map((f: Record<string, unknown>) => ({
          flag: f.flag, severity: f.severity,
          clauses: f.clauses ?? [], evidence: f.evidence ?? [],
        })),
      claims: (r.claims ?? []).map((c: Record<string, string>) => {
        const it = items.get(c?.source_url);
        return {
          claim: c?.claim ?? "",
          url: c?.source_url ?? "",
          title: it?.title ?? "",
          title_en: it?.title_en ?? "",
          lang: it?.lang ?? "",
        };
      }),
    })),
  };
}

async function decide(id: number, decision: string, reason: string) {
  if (!id || !["approved", "revise", "killed"].includes(decision)) {
    throw new Error(`bad decision: id=${id} decision=${decision}`);
  }
  const { error } = await sb.from("reports").update({
    editor_decision: decision,
    editor_reason: reason || null,
    decided_at: new Date().toISOString(),
  }).eq("id", id);
  if (error) throw new Error(`update report ${id}: ${error.message}`);

  // Approving is the ONLY thing that releases a held email. `revise` and `killed` both leave it
  // held, which is what "do not send this" means -- a revise needs a new draft, not this one.
  let released = 0;
  if (decision === "approved") {
    const { data } = await sb.from("outbox")
      .update({ held: false }).eq("report_id", id).select("id");
    released = (data ?? []).length;
  }
  await note("info", `decision: ${decision} on report ${id}`, { id, decision, reason, released });
  return { ok: true, id, decision, released };
}

Deno.serve(async (req) => {
  if (req.method !== "POST") return json({ error: "POST only" }, 405);
  if (!(await secretOk(req))) return json({ error: "forbidden" }, 403);

  let payload: Record<string, unknown> = {};
  try {
    payload = await req.json();
  } catch {
    return json({ error: "body must be JSON" }, 400);
  }
  const action = String(payload.action ?? "");

  try {
    if (action === "list") return json(await list());
    if (action === "decide") {
      return json(await decide(Number(payload.id), String(payload.decision ?? ""),
                               String(payload.reason ?? "").slice(0, 2000)));
    }
    if (action === "log") {
      // The client names itself. This used to be hardcoded "apps-script", which meant every row
      // the Cloudflare Worker wrote was filed under a client that no longer exists -- in the one
      // table you go to when you are trying to work out what actually happened.
      const source = String(payload.source ?? "review-client").slice(0, 64);
      await note(String(payload.level ?? "info"), String(payload.message ?? "").slice(0, 4000),
                 payload.context ?? {}, source);
      return json({ ok: true });
    }
    return json({ error: `unknown action: ${action}` }, 400);
  } catch (e) {
    // Surface failures in app_log too -- a browser client cannot show a stack trace to anyone who
    // is not sitting in front of it with devtools open.
    await note("error", `action ${action} failed: ${e instanceof Error ? e.message : String(e)}`,
               { action, payload });
    return json({ error: e instanceof Error ? e.message : String(e) }, 500);
  }
});
