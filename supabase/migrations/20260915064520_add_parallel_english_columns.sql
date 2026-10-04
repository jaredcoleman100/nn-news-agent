-- Parallel English alongside the source language, across items and reports.
--
-- Additive only. `items` is shared by both newsrooms (an item is owned by its source, not by a
-- desk), so these columns appear for nord-norge and rikspolitikk alike -- which is intended: the
-- translation is a property of the item, not of the desk reading it. Nothing here rewrites an
-- existing value, so the cross-newsroom guard on `beats` is not implicated.

alter table items add column if not exists title_en text;
alter table items add column if not exists body_en  text;
-- Detected source language (BCP-47-ish: nb, nn, se, ru, fi, en, de, sv). Written by the
-- translator, not by the source config, because no source declares one and rikspolitikk
-- deliberately ingests five languages.
alter table items add column if not exists lang     text;

comment on column items.title_en is 'English rendering of title. Null = not yet translated.';
comment on column items.body_en  is 'English rendering of body. Null = not yet translated.';
comment on column items.lang     is 'Detected source language of title/body.';

-- The translate queue. Partial index so the "what still needs English?" scan stays cheap as the
-- table grows; it shrinks to nothing once the backlog is drained.
create index if not exists items_untranslated_idx
  on items (fetched_at) where title_en is null;

-- Draft.sections was generated on every run and then dropped on the floor: to_row() never wrote
-- it, so the English half of every digest existed only inside the sent email and could not be
-- re-read, re-rendered or audited. Persist it.
alter table reports add column if not exists sections jsonb not null default '{}'::jsonb;

comment on column reports.sections is
  'Draft.sections as produced, including body_en and any _en twins. Was previously discarded.';
