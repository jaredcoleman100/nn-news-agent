# supabase/legacy — retired, do not run

These three files were in `supabase/migrations/` until 2026-09-14 but were **never the applied
history**. They are kept for provenance, not for use. The real chain is `supabase/quickstart.sql`
followed by the nine tracked migrations in `supabase/migrations/`.

Each is wrong about the live database in a way that matters:

**`001_schema.sql`** — declares `vector(384)` (gte-small) and a one-argument
`match_beats(query_embedding vector(384))`. The deployment is `vector(768)` (gemini) and
`match_beats` takes a `newsroom` argument. It also predates every `newsroom_id` column.

**`002_products_jobs.sql`** — cannot run against this database. `jobs` already exists from
`quickstart.sql`, so `create table jobs` fails partway through, which is exactly why
`20260914071254_add_outbox_for_email_delivery.sql` exists: it extracts the one piece of `002` that
was actually needed. It also creates a `precedent` table, which does not exist in the live database;
the reference corpus (`reference_docs` + `reference_chunks`) replaced that idea.

**`003_embed_dim.sql`** — **destructive.** It is a template for switching embedder, not a migration:
it does `alter column embedding type vector(N) using null`, which **discards every stored embedding**,
and its header tells you to set the width by hand first (bge-m3 = 1024, gemini = 768,
gte-small = 384). It was committed reading 1024 while the deployment runs 768, so running it as it
stood would have wiped all embeddings *and* set the wrong width, breaking every insert afterwards.
The literal has been corrected to 768 so that it at least matches reality, but the `using null`
wipe is inherent to what the script does.

If you genuinely need to switch embedder: edit the width, run it, then re-seed
(`run.py --seed`) and re-embed. Budget for the re-embedding cost, and expect
`rebuild_hits(newsroom)` afterwards to restore hits from the new vectors.
