-- Run ONCE when switching embedder. Set the width to EMBED_DIM (bge-m3 = 1024, gemini = 768, gte-small = 384),
-- then re-run worker/seed.py and let worker/embed_and_score.py re-embed items (embedding is nulled here).
alter table items     alter column embedding type vector(768) using null;
alter table beats     alter column embedding type vector(768) using null;
alter table precedent alter column embedding type vector(768) using null;
drop function if exists match_beats(vector);
drop function if exists match_beats(vector, text);
create or replace function match_beats(query_embedding vector(768), newsroom text default null)
returns table (beat_id text, score real) language sql stable as $$
  -- the beats table is shared across newsrooms; without this filter every item is scored
  -- against every desk's beats
  select id, 1 - (embedding <=> query_embedding) as score from beats
  where active and embedding is not null and (newsroom is null or newsroom_id = newsroom)
  order by embedding <=> query_embedding $$;
drop function if exists related_items(vector, int, int);
drop function if exists related_items(vector, int, int, text);
create or replace function related_items(query_embedding vector(768), days int default 14,
                                         k int default 8, newsroom text default null)
returns setof items language sql stable as $$
  -- `items` has no newsroom_id; provenance is only via source_id. Without the join a
  -- second newsroom's articles leak into drafting context. LEFT JOIN so an item with an
  -- unknown source is excluded when a newsroom is specified, not silently included.
  select i.* from items i
    left join sources s on s.id = i.source_id
  where i.published_at > now() - make_interval(days => days)
    and i.embedding is not null
    and (newsroom is null or s.newsroom_id = newsroom)
  order by i.embedding <=> query_embedding
  limit k $$;
create index on items using ivfflat (embedding vector_cosine_ops) with (lists = 100);
