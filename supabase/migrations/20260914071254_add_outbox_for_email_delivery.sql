-- Email delivery queue. From migration 002, extracted alone: `jobs` already exists
-- from quickstart.sql, so running all of 002 would fail on create table jobs.
-- `precedent` is deliberately omitted; it is only used by the Slack-reactions handler.
create table if not exists outbox (
  id bigserial primary key,
  "to" text[] not null,
  subject text not null,
  mime text not null,
  body text not null,
  report_id bigint references reports(id),
  sent_at timestamptz,
  created_at timestamptz default now()
);

-- Drain queue efficiently: the Edge Function selects unsent rows oldest-first.
create index if not exists outbox_unsent_idx on outbox (created_at) where sent_at is null;

-- Matches the other 8 tables: RLS on, no policies, so only the service role reaches it.
-- Report bodies and recipient addresses must not be readable by anon/publishable keys.
alter table outbox enable row level security;
