# supabase/migrations

These nine files are the **real applied history**, exported verbatim from
`supabase_migrations.schema_migrations` on 2026-09-14. Filenames are the tracked version and name, so
the directory and the database agree; `mcp list_migrations` returns exactly this list.

## Rebuild order

1. `supabase/quickstart.sql` — the base schema (sources, items, beats, hits, jobs, reports, runs,
   config), `vector(768)`, `newsroom_id` on every table that needs it. This is what the README's
   Quickstart tells you to paste into the SQL editor, and it is what was actually run.
2. These nine migrations, in filename order. They add `outbox`, pg_cron/pg_net, `sources.note`,
   `sources.config`, the reference corpus, and the newsroom scoping of `match_beats`,
   `related_items` and `rebuild_hits`.

Together those reproduce the live schema. The live tables are exactly beats, config, hits, items,
jobs, outbox, reference_chunks, reference_docs, reports, runs, sources.

**Embedding width changed the same day.** `20260914182554_switch_embeddings_to_bge_m3_1024` moved
every vector column from `vector(768)` (gemini) to `vector(1024)` (bge-m3) and nulled the stored
vectors, as that operation always does. Anything asserting 768 — including an earlier version of
this file — is describing the database as it was before 18:25 UTC on 2026-09-14. Check
`format_type` against `pg_attribute` rather than trusting any prose, this file included.

## Why the directory looked wrong before

Until 2026-09-14 this directory held `001_schema.sql`, `002_products_jobs.sql` and
`003_embed_dim.sql` and **none of the nine below**. Those three were a parallel track that was never
the applied history — `20260914071254_add_outbox_for_email_delivery.sql` says so in its own comment:
`jobs` already existed from `quickstart.sql`, so running all of `002` would have failed on
`create table jobs`, and `precedent` was deliberately skipped. It has since been retired and does not
exist in the database.

They have moved to `supabase/legacy/`. Read that directory's README before running anything in it.

The lesson worth keeping: a file sitting in `migrations/` is an instruction to run it. Anything that
is not part of the applied history does not belong here, however historically interesting it is.

> **Two newsrooms share this database.** Before altering a shared table — especially the
> `vector(1024)` embedding columns, which cannot be changed without wiping both desks — read
> [SHARED-DATABASE.md](../SHARED-DATABASE.md).
