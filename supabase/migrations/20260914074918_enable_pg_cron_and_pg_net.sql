-- Needed to drain `outbox` on a schedule: pg_cron runs the job, pg_net makes the
-- async HTTP call to the send-outbox Edge Function.
create extension if not exists pg_net with schema extensions;
create extension if not exists pg_cron;
