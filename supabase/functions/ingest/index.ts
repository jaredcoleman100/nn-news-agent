// Supabase Edge Function: poll RSS sources, embed, score against beats, insert hits.
// Schedule hourly with pg_cron/`supabase functions schedule`. Uses the built-in
// gte-small embedder (384-dim) for v0; swap for a multilingual model later.
import { createClient } from "npm:@supabase/supabase-js@2";
import { parseFeed } from "https://deno.land/x/rss@1.0.0/mod.ts";

const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
const embedder = new Supabase.ai.Session("gte-small");

async function embed(text: string): Promise<number[]> {
  return await embedder.run(text.slice(0, 2000), { mean_pool: true, normalize: true }) as number[];
}

Deno.serve(async () => {
  const { data: cfg } = await sb.from("config").select("value").eq("key", "paused").single();
  if (cfg?.value === true) return new Response("paused");

  const { data: sources } = await sb.from("sources").select("*").eq("active", true).eq("kind", "rss");
  let inserted = 0, hits = 0;

  for (const src of sources ?? []) {
    try {
      const xml = await (await fetch(src.url, { headers: { "User-Agent": "nn-news-agent/0.1" } })).text();
      const feed = await parseFeed(xml);
      for (const e of feed.entries) {
        const url = e.links?.[0]?.href ?? e.id;
        if (!url) continue;
        const title = e.title?.value ?? "";
        const body = (e.description?.value ?? e.content?.value ?? "").replace(/<[^>]+>/g, " ");
        const text = `${title}\n${body}`;
        const embedding = await embed(text);
        const { data: item, error } = await sb.from("items")
          .insert({ source_id: src.id, url, title, body, published_at: e.published ?? e.updated, embedding })
          .select("id").single();
        if (error || !item) continue;           // duplicate → skip
        inserted++;
        const { data: matches } = await sb.rpc("match_beats", { query_embedding: embedding });
        const { data: beats } = await sb.from("beats").select("id, threshold");
        const th = Object.fromEntries((beats ?? []).map((b: any) => [b.id, b.threshold]));
        const { data: capRow } = await sb.from("config").select("value").eq("key", "max_beats_per_item").single();
        const cap = Number(capRow?.value ?? 1);
        // Best-matching beats only: each hit becomes a separate editor memo.
        const over = (matches ?? []).filter((m: any) => m.score >= th[m.beat_id])
          .sort((a: any, b: any) => b.score - a.score).slice(0, cap);
        for (const m of over) {
          await sb.from("hits").insert({ item_id: item.id, beat_id: m.beat_id, score: m.score });
          hits++;
        }
      }
      await sb.from("sources").update({ last_polled_at: new Date().toISOString() }).eq("id", src.id);
    } catch (err) { console.error(src.name, err); }
  }
  return Response.json({ inserted, hits });
});
