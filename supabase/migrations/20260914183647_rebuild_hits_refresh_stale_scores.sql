-- rebuild_hits converged on the desired set to preserve status, but surviving rows kept the
-- score they were inserted with. After the bge-m3 switch that left hits carrying gemini-era
-- scores: max_score read 0.712 when the new embedding space cannot exceed 0.603. The editor
-- memo shows that number, so a stale score is misleading provenance, not a cosmetic issue.
-- Refresh the score on surviving rows while still preserving status and editor_feedback.
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
  select item_id, beat_id, score from pairs where trust_hint and beat_id = beat_hint
  union all
  select item_id, beat_id, score from (
    select item_id, beat_id, score,
           row_number() over (partition by item_id order by score desc) as rn
    from pairs where not trust_hint and score >= threshold
  ) t where rn <= cap;

  delete from hits h
   using items it join sources s on s.id = it.source_id
   where h.item_id = it.id and s.newsroom_id = newsroom
     and not exists (select 1 from _want w
                     where w.item_id = h.item_id and w.beat_id = h.beat_id);
  get diagnostics d = row_count;

  insert into hits (item_id, beat_id, score, newsroom_id)
  select w.item_id, w.beat_id, w.score, newsroom from _want w
  on conflict (item_id, beat_id) do nothing;
  get diagnostics i = row_count;

  -- surviving rows: refresh the score, keep status and editor_feedback
  update hits h set score = w.score
    from _want w
   where h.item_id = w.item_id and h.beat_id = w.beat_id
     and h.score is distinct from w.score;

  return query select i, d;
end $$;

select * from rebuild_hits('nord-norge');
