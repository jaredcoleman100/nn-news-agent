-- Two newsrooms share this project (nord-norge, rikspolitikk) and match_beats filtered only
-- on `active`, so every item was scored against BOTH sets of beats. Measured: 73 of 106 hits
-- on a Nord-Norge run were against rikspolitikk beats. Silent, and editorially wrong in both
-- directions.
--
-- Replace the 1-arg function with a 2-arg one carrying a default, so existing 1-arg callers
-- (the ingest Edge Function, worker/embed_and_score.py) keep working while Python callers
-- that pass the newsroom get correct scoping. Dropping first avoids an ambiguous overload.
drop function if exists match_beats(vector);
drop function if exists match_beats(vector, text);

create or replace function match_beats(query_embedding vector(768), newsroom text default null)
returns table (beat_id text, score real) language sql stable as $$
  select id, 1 - (embedding <=> query_embedding) as score
  from beats
  where active and embedding is not null
    and (newsroom is null or newsroom_id = newsroom)
  order by embedding <=> query_embedding $$;
