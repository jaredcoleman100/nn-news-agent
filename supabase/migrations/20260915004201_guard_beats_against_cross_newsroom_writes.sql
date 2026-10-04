-- 20260915004201_guard_beats_against_cross_newsroom_writes.sql
--
-- Two newsrooms (nord-norge, rikspolitikk) are separate projects with different owners sharing
-- this database, separated only by beats.newsroom_id. On 2026-09-14 an unscoped
-- `update beats set threshold = 0.5` intended for one desk retuned all nine beats of the other;
-- its hits fell from 47 to 26 with no error. Documentation did not prevent it, so the table does.
--
-- A statement-level trigger cannot see whether a WHERE clause was written, but it can see that one
-- statement changed rows belonging to more than one newsroom, which is the actual failure mode.
-- Every legitimate write here is single-newsroom: seed() upserts one beat at a time, and a
-- threshold retune belongs to one desk. Triggers are not bypassed by the service-role key, which
-- is what both desks connect with, so this is the only layer that can hold (RLS cannot).

create or replace function guard_beats_single_newsroom() returns trigger
language plpgsql as $$
declare
  rooms text;
  n int;
begin
  -- Deliberate cross-desk maintenance stays possible, but has to say so out loud.
  if coalesce(current_setting('nn.allow_cross_newsroom', true), 'off') = 'on' then
    return null;
  end if;
  select count(distinct newsroom_id), string_agg(distinct newsroom_id, ', ')
    into n, rooms from changed;
  if n > 1 then
    raise exception
      'refused: one statement would change beats in % newsrooms (%). These are separate '
      'newsrooms with different owners; scope the write with "where newsroom_id = ...". '
      'Thresholds are per-desk and not interchangeable (nord-norge 0.48, rikspolitikk 0.5) '
      '- see supabase/SHARED-DATABASE.md. If the cross-desk change is intended, run '
      '"set local nn.allow_cross_newsroom = ''on'';" first, in the same transaction.',
      n, rooms;
  end if;
  return null;
end $$;

drop trigger if exists beats_single_newsroom_update on beats;
create trigger beats_single_newsroom_update
  after update on beats
  referencing new table as changed
  for each statement execute function guard_beats_single_newsroom();

drop trigger if exists beats_single_newsroom_delete on beats;
create trigger beats_single_newsroom_delete
  after delete on beats
  referencing old table as changed
  for each statement execute function guard_beats_single_newsroom();
