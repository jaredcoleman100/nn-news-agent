-- Same root cause as the match_beats leak: `items` has no newsroom_id of its own, it is
-- reachable only through source_id, so related_items pulled the rikspolitikk desk's articles
-- into Nord-Norge drafting context. Less damaging than wrong beats (context pollution rather
-- than mis-filed stories) but the same bug.
--
-- LEFT JOIN on purpose: an item with a null source_id has unknown provenance, so it is
-- excluded whenever a newsroom is specified rather than silently included.
drop function if exists related_items(vector, int, int);
drop function if exists related_items(vector, int, int, text);

create or replace function related_items(query_embedding vector(768), days int default 14,
                                         k int default 8, newsroom text default null)
returns setof items language sql stable as $$
  select i.* from items i
    left join sources s on s.id = i.source_id
  where i.published_at > now() - make_interval(days => days)
    and i.embedding is not null
    and (newsroom is null or s.newsroom_id = newsroom)
  order by i.embedding <=> query_embedding
  limit k $$;
