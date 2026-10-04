-- A similarity threshold is only meaningful for the embedding model it was tuned against.
--
-- 0.60 was calibrated for gemini-embedding-001 at 768 dimensions. After
-- 20260914182554_switch_embeddings_to_bge_m3_1024, measured over all 776 re-embedded items, the
-- best-beat score for ANY item peaked at 0.644 (rikspolitikk) and 0.603 (nord-norge), with medians
-- near 0.42. Exactly one item per newsroom could clear 0.60, so scoring had silently stopped:
-- rebuild_hits('rikspolitikk') deleted 182 hits and inserted none, leaving that desk with 1.
--
-- 0.50 sits near p90 of the new distribution: ~49 of 455 rikspolitikk items and ~26 of 321
-- nord-norge items over roughly four days of corpus, i.e. about 12 and 6 a day.
--
-- The switch was still worth making. Under gemini the top-ranked rikspolitikk item was an Altinget
-- housekeeping post ("Takk til alle dere som har lest, abonnert...") at 0.695; under bge-m3 it does
-- not reach the top twelve, which are on-beat political items. Better ranking, different scale.
--
-- The column default matters as much as the data: run.py seed() upserts beats without a threshold,
-- so existing rows keep whatever is set here but any NEW beat would otherwise be created at the old
-- default and be dead on arrival.
alter table beats alter column threshold set default 0.50;

update beats set threshold = 0.50 where threshold is distinct from 0.50;
