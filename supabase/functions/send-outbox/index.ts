// Edge Function: send queued emails from `outbox`. Schedule every 5 min. Uses Resend (RESEND_API_KEY, MAIL_FROM);
// swap the send() body for Gmail API or SMTP if preferred. Markdown bodies are sent as text + minimal HTML.
import { createClient } from "npm:@supabase/supabase-js@2";
const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);

function toHtml(md: string): string {
  return md.replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/^# (.*)$/gm, "<h1>$1</h1>").replace(/^## (.*)$/gm, "<h2>$1</h2>")
    .replace(/\*\*(.*?)\*\*/g, "<b>$1</b>").replace(/^- (.*)$/gm, "<li>$1</li>").replace(/\n\n/g, "<br><br>");
}

async function send(to: string[], subject: string, text: string): Promise<boolean> {
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${Deno.env.get("RESEND_API_KEY")}`, "Content-Type": "application/json" },
    body: JSON.stringify({ from: Deno.env.get("MAIL_FROM"), to, subject, text, html: toHtml(text) }),
  });
  return r.ok;
}

Deno.serve(async () => {
  // `held` rows are queued but gated: the report came back `blocked` and is waiting for an editor
  // to approve it in the `review` function. Without this filter the hold does nothing, because the
  // row is already sitting here fully rendered and ready to go.
  const { data: rows } = await sb.from("outbox")
    .select("*").is("sent_at", null).eq("held", false).order("created_at").limit(20);
  let sent = 0;
  for (const row of rows ?? []) {
    if (await send(row.to, row.subject, row.body)) {
      await sb.from("outbox").update({ sent_at: new Date().toISOString() }).eq("id", row.id);
      sent++;
    }
  }
  return Response.json({ sent });
});
