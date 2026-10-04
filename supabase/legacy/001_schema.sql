-- Northern Norway news agent — core schema
create extension if not exists vector;

create table sources (
  id serial primary key,
  name text not null,
  kind text not null check (kind in ('rss','api','scrape','social')),
  url text not null unique,
  beat_hint text,                 -- optional beat id this source mostly feeds
  active boolean default true,
  last_polled_at timestamptz
);

create table items (
  id bigserial primary key,
  source_id int references sources(id),
  url text not null,
  title text,
  body text,
  published_at timestamptz,
  fetched_at timestamptz default now(),
  lang text,
  embedding vector(384),
  unique (source_id, url)          -- idempotency
);
create index on items using ivfflat (embedding vector_cosine_ops) with (lists = 100);
create index on items (published_at desc);

create table beats (
  id text primary key,             -- matches corpus/beats.json ids
  name text not null,
  description text not null,
  keywords text[] not null,
  ethics_profile jsonb not null,
  threshold real not null default 0.78,
  embedding vector(384),
  active boolean default true
);

create table hits (
  id bigserial primary key,
  item_id bigint references items(id),
  beat_id text references beats(id),
  score real not null,
  status text not null default 'new' check (status in ('new','processing','reported','rejected','failed')),
  editor_feedback text check (editor_feedback in ('accept','reject','irrelevant')),
  created_at timestamptz default now(),
  unique (item_id, beat_id)
);

create table reports (
  id bigserial primary key,
  hit_id bigint references hits(id),
  beat_id text references beats(id),
  headline text,
  body text not null,
  ethics_memo jsonb not null,
  gate text not null check (gate in ('blocked','review','clear')),
  screen_result jsonb not null,    -- raw output of screen_report, for audit
  revision int default 1,
  slack_ts text,
  editor_decision text check (editor_decision in ('approve','revise','kill')),
  created_at timestamptz default now()
);

create table runs (
  id bigserial primary key,
  hit_id bigint references hits(id),
  started_at timestamptz default now(),
  finished_at timestamptz,
  status text,
  model text,
  input_tokens int, output_tokens int,
  steps jsonb,                     -- ordered log of every step and tool call
  error text
);

create table config (key text primary key, value jsonb not null);
insert into config values ('paused', 'false'), ('max_runs_per_hour', '20');

-- nearest beats for an item
create or replace function match_beats(query_embedding vector(384))
returns table (beat_id text, score real) language sql stable as $$
  select id, 1 - (embedding <=> query_embedding) as score
  from beats where active and embedding is not null
  order by embedding <=> query_embedding
$$;

-- related recent items in a beat, for report context
create or replace function related_items(query_embedding vector(384), days int default 14, k int default 8)
returns setof items language sql stable as $$
  select * from items
  where published_at > now() - make_interval(days => days)
  order by embedding <=> query_embedding limit k
$$;

-- fire the worker when a hit lands (configure as Database Webhook on hits INSERT in the dashboard)
