-- Multi-product, multi-newsroom
alter table sources add column newsroom_id text not null default 'nord-norge';
alter table beats   add column newsroom_id text not null default 'nord-norge';
alter table hits    add column newsroom_id text not null default 'nord-norge';
alter table config  add column newsroom_id text not null default 'nord-norge';

create table jobs (
  id bigserial primary key,
  newsroom_id text not null,
  product_id text not null,
  trigger text not null,
  payload jsonb not null,
  created_at timestamptz default now()
);

alter table reports add column job_id bigint references jobs(id);
alter table reports add column product_id text;
alter table reports add column newsroom_id text not null default 'nord-norge';
alter table reports add column claims jsonb;
alter table reports add column versions jsonb;
alter table reports add column editor_reason text;
alter table reports alter column hit_id drop not null;

alter table runs add column job_id bigint references jobs(id);
alter table runs add column report_id bigint references reports(id);

create table outbox (
  id bigserial primary key,
  "to" text[] not null,
  subject text not null,
  mime text not null,
  body text not null,
  report_id bigint references reports(id),
  sent_at timestamptz,
  created_at timestamptz default now()
);

-- house precedent: editor decisions become retrievable
create table precedent (
  id bigserial primary key,
  newsroom_id text not null,
  report_id bigint references reports(id),
  decision text not null check (decision in ('approve','revise','kill')),
  reason text,
  fact_pattern jsonb,          -- flags + identifiers from the memo, for fact-pattern retrieval
  embedding vector(384),
  created_at timestamptz default now()
);
create index on precedent using ivfflat (embedding vector_cosine_ops) with (lists = 50);
