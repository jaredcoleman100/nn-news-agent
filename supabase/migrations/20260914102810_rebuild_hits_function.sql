-- Rebuild one newsroom's hits from embeddings already stored. No embedding cost, no Python
-- round-trip for 776 vectors. Needed whenever scoring rules change: a threshold edit, a beat
-- re-seed, or a scoring bug like the cross-newsroom leak this was written to repair.
--
-- Implements the same three rules as run.py score(): newsroom scoping, trust_hint for
-- pre-vetted narrow sources, and the max_beats_per_item fan-out cap.
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

  delete from hits h
   using items it join sources s on s.id = it.source_id
   where h.item_id = it.id and s.newsroom_id = newsroom;
  get diagnostics d = row_count;

  with pairs as (
    select it.id as item_id, b.id as beat_id,
           (1 - (it.embedding <=> b.embedding))::real as score,
           b.threshold, s.beat_hint,
           coalesce((s.config ->> 'trust_hint')::boolean, false) as trust_hint
    from items it
    join sources s on s.id = it.source_id and s.newsroom_id = newsroom
    join beats b on b.newsroom_id = newsroom and b.active and b.embedding is not null
    where it.embedding is not null
  ),
  picked as (
    -- a pre-vetted narrow outlet: the editorial judgement is already made
    select item_id, beat_id, score from pairs where trust_hint and beat_id = beat_hint
    union all
    -- otherwise the best-matching beats over their own threshold, capped
    select item_id, beat_id, score from (
      select item_id, beat_id, score,
             row_number() over (partition by item_id order by score desc) as rn
      from pairs where not trust_hint and score >= threshold
    ) t where rn <= cap
  )
  insert into hits (item_id, beat_id, score, newsroom_id)
  select p.item_id, p.beat_id, p.score, newsroom from picked p
  on conflict (item_id, beat_id) do nothing;
  get diagnostics i = row_count;

  return query select i, d;
end $$;
