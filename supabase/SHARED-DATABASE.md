# One database, two newsrooms — read before writing

`nord-norge` (regional news desk) and `rikspolitikk` (national-politics satire desk) are
**separate projects with different owners** that share a single Supabase project. They are
separated only by a `newsroom_id` column. `beats`, `items`, `hits`, `sources`, `reports` and
`reference_docs` are all shared tables.

Nothing in the schema enforces that separation, so an unscoped write silently reconfigures
someone else's newsroom.

## Scope every write

```sql
-- WRONG: retunes both desks, no error, no warning
update beats set threshold = 0.5;

-- RIGHT
update beats set threshold = 0.5 where newsroom_id = 'rikspolitikk';
```

This is not hypothetical. On 2026-09-14 a global `update beats set threshold = 0.5` intended for
rikspolitikk also moved all nine nord-norge beats off their measured value, and nord-norge's hits
fell from 47 to 26 — discovered only by chance. Restored with a scoped update plus
`select rebuild_hits('nord-norge')`.

**Thresholds are per-desk and are not interchangeable.** Each was derived from its own desk's
score distribution against its own beat text:

| newsroom | threshold | basis |
|---|---|---|
| `nord-norge` | **0.48** | p98 of 2889 measured pairs (min 0.131, mean 0.357, p95 0.454, max 0.603) |
| `rikspolitikk` | 0.5 | set by that desk's owner |

## The `beats` table now refuses cross-desk writes

Documentation alone did not hold, so this is enforced in the database
(`20260915004201_guard_beats_against_cross_newsroom_writes`). A statement-level trigger on
`beats` rejects any single UPDATE or DELETE whose rows span more than one newsroom:

```
ERROR: refused: one statement would change beats in 2 newsrooms (nord-norge, rikspolitikk).
       These are separate newsrooms with different owners; scope the write with
       "where newsroom_id = ...".
```

Single-desk writes are unaffected, including `seed()`, which upserts one beat at a time. If a
cross-desk change really is intended, say so explicitly in the same transaction:

```sql
begin;
set local nn.allow_cross_newsroom = 'on';
update beats set active = true;   -- now permitted
commit;
```

Note that triggers still apply to the **service-role key**, which is what both desks connect with.
RLS would not help here: the service-role key bypasses it entirely.

## The embedding dimension is the dangerous one

`items.embedding`, `beats.embedding` and `reference_chunks.embedding` are **one global schema
fact**. The whole system is on `bge-m3` via local Ollama at **1024-d** (`EMBEDDER=ollama`,
`EMBED_DIM=1024`).

Changing that dimension is **destructive and not reversible**:
`alter column embedding type vector(N) using null` nulls *every* row, both desks at once. Widening
768 to 1024 is what nulled the rikspolitikk desk in the first place. If you need a different
dimension, that is a conversation with the other desk's owner, not a migration.

Do not run `supabase/legacy/003_embed_dim.sql`. It was never applied history, references a
`precedent` table that does not exist, predates `reference_chunks`, and would revert the newsroom
scoping of `match_beats` and `related_items`.

## Newsroom-scoped RPCs

`match_beats(query_embedding, newsroom)`, `related_items(..., newsroom)` and
`match_reference(...)` take a newsroom argument precisely because the tables are shared. Omitting
it on `match_beats` ranks against the *other* desk's beats too — this caused 73 of 106 hits to be
assigned wrongly before it was fixed. Always pass it.

## Cross-checks worth running before you trust a hit count

```sql
select newsroom_id, threshold, count(*) from beats group by 1,2 order by 1,2;
select newsroom_id, count(*), min(score), max(score) from hits group by 1 order by 1;
```

A score above 0.61 on either desk means a stale pre-bge-m3 row: the old
`gemini-embedding-001` 768-d space produced values up to ~0.71 that cannot occur now.
