-- Surgical repair first: drop only hits whose item and beat belong to different newsrooms.
-- Deliberately not via rebuild_hits, because the rikspolitikk desk has hits in 'processing'
-- and 'reported' states and a delete+reinsert would return them to 'new' and re-notify.
delete from hits h
 using items i, sources s, beats b
 where h.item_id = i.id and s.id = i.source_id and b.id = h.beat_id
   and s.newsroom_id <> b.newsroom_id;

-- And make rebuild_hits safe to run on a newsroom that has already reported: converge on the
-- desired set instead of recreating it, so a surviving (item_id, beat_id) keeps its status.
create or replace function rebuild_hits(newsroom text)
returns table (inserted integer, deleted integer)
language plpgsql as $$
declare
  d integer := 0;
  i integer := 0;
  cap integer;
begin
  select coalesce((value #>> '{}')::int, 1) into cap from config where key = 'max_beats_per_item';
  cap := coalesce(cap, 1);

  create temp table _want on commit drop as
  with pairs as (
    select it.id as item_id, b.id as beat_id,
           (1 - (it.embedding <=> b.embedding))::real as score,
           b.threshold, s.beat_hint,
           coalesce((s.config ->> 'trust_hint')::boolean, false) as trust_hint
    from items it
    join sources s on s.id = it.source_id and s.newsroom_id = newsroom
    join beats b on b.newsroom_id = newsroom and b.active and b.embedding is not null
    where it.embedding is not null
  )
  -- a pre-vetted narrow outlet: the editorial judgement is already made
  select item_id, beat_id, score from pairs where trust_hint and beat_id = beat_hint
  union all
  -- otherwise the best-matching beats over their own threshold, capped
  select item_id, beat_id, score from (
    select item_id, beat_id, score,
           row_number() over (partition by item_id order by score desc) as rn
    from pairs where not trust_hint and score >= threshold
  ) t where rn <= cap;

  -- remove hits this newsroom should no longer have
  delete from hits h
   using items it join sources s on s.id = it.source_id
   where h.item_id = it.id and s.newsroom_id = newsroom
     and not exists (select 1 from _want w
                     where w.item_id = h.item_id and w.beat_id = h.beat_id);
  get diagnostics d = row_count;

  -- add the missing ones; untouched rows keep their status and editor_feedback
  insert into hits (item_id, beat_id, score, newsroom_id)
  select w.item_id, w.beat_id, w.score, newsroom from _want w
  on conflict (item_id, beat_id) do nothing;
  get diagnostics i = row_count;

  return query select i, d;
end $$;
