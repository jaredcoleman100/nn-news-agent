-- Per-source options for non-RSS adapters. The sitemap adapter needs include/exclude URL
-- patterns because High North News publishes opinion and sport beside news, and a monitor
-- must not draft reports on either. Keys: days, limit, include, exclude, sub.
alter table sources add column if not exists config jsonb default '{}'::jsonb;
