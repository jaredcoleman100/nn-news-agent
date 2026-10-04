-- Why a source is inactive belongs next to the source, not in a commit message.
alter table sources add column if not exists note text;

-- Fan-out cap: match_beats returns every beat over threshold, so one broad story
-- became a hit (and therefore a separate editor memo) under several beats at once.
-- Observed 2.17 beats/item on the first real run.
insert into config (key, value) values ('max_beats_per_item', '1'::jsonb)
on conflict (key) do update set value = excluded.value;
