-- Quickstart schema for run.py (single-process mode). Vector width 768 = Gemini embeddings.
create extension if not exists vector;
create table if not exists sources (id serial primary key, name text, kind text default 'rss', url text unique, beat_hint text, active boolean default true, last_polled_at timestamptz, newsroom_id text default 'nord-norge');
create table if not exists items (id bigserial primary key, source_id int references sources(id), url text, title text, body text, published_at timestamptz, fetched_at timestamptz default now(), embedding vector(768), unique (source_id, url));
create table if not exists beats (id text primary key, name text, description text, keywords text[], ethics_profile jsonb, threshold real default 0.60, embedding vector(768), active boolean default true, newsroom_id text default 'nord-norge');
create table if not exists hits (id bigserial primary key, item_id bigint references items(id), beat_id text references beats(id), score real, status text default 'new', editor_feedback text, created_at timestamptz default now(), newsroom_id text default 'nord-norge', unique (item_id, beat_id));
create table if not exists jobs (id bigserial primary key, newsroom_id text, product_id text, trigger text, payload jsonb, created_at timestamptz default now());
create table if not exists reports (id bigserial primary key, job_id bigint references jobs(id), hit_id bigint references hits(id), product_id text, newsroom_id text, headline text, body text, claims jsonb, ethics_memo jsonb, gate text, screen_result jsonb, revision int, versions jsonb, slack_ts text, editor_decision text, editor_reason text, created_at timestamptz default now());
create table if not exists runs (id bigserial primary key, job_id bigint, report_id bigint, hit_id bigint, started_at timestamptz default now(), finished_at timestamptz, status text, steps jsonb, input_tokens int, output_tokens int, error text);
create table if not exists config (key text primary key, value jsonb, newsroom_id text default 'nord-norge');
insert into config (key, value) values ('paused','false'), ('max_reports_per_run','5') on conflict do nothing;

create or replace function match_beats(query_embedding vector(768))
returns table (beat_id text, score real) language sql stable as $$
  select id, 1 - (embedding <=> query_embedding) as score from beats where active and embedding is not null
  order by embedding <=> query_embedding $$;
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
