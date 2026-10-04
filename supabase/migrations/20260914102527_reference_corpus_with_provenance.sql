-- Background reference corpus: strategy documents, official reports, statistics releases.
-- Deliberately NOT the `items` table. An item becomes a hit and then a drafted news report;
-- a 2024 strategy PDF must never do that. These rows are retrieved as context only.
--
-- Provenance is enforced, not conventional, because reference/README.md records the failure
-- mode: a synthesised analysis with unattributed figures was already used to derive beats.json.
-- An internal corpus reads as authoritative to the drafter, and the single_source screen will
-- not fire on "our own reference document said so".
create table if not exists reference_docs (
  id           bigserial primary key,
  newsroom_id  text not null default 'nord-norge',
  title        text not null,
  publisher    text not null,                       -- who published it, not who cited it
  url          text not null unique,
  doc_date     date,                                -- when the DOCUMENT is dated
  retrieved_at timestamptz not null default now(),  -- when we pulled it
  -- primary: the issuing body's own text (DoD, NOAA, SSB, Storting).
  -- secondary: credible reporting or peer-reviewed work about it.
  -- unverified: synthesised or uncited material; usable for orientation, never as a fact.
  tier         text not null check (tier in ('primary', 'secondary', 'unverified')),
  verified     boolean not null default false,      -- a human checked it against the source
  license_note text,
  sha256       text,                                -- detect silent revisions of the source
  created_at   timestamptz not null default now()
);

create table if not exists reference_chunks (
  id        bigserial primary key,
  doc_id    bigint not null references reference_docs(id) on delete cascade,
  ord       int not null,
  text      text not null,
  embedding vector(768),                            -- same width as items/beats
  unique (doc_id, ord)
);

create index if not exists reference_chunks_doc_idx on reference_chunks (doc_id);

-- Retrieval returns provenance alongside the text so a memo can never cite a chunk without
-- saying where it came from and whether anyone verified it.
create or replace function match_reference(query_embedding vector(768), k int default 6)
returns table (chunk_id bigint, doc_id bigint, ord int, text text, score real,
               title text, publisher text, url text, doc_date date, tier text, verified boolean)
language sql stable as $$
  select c.id, d.id, c.ord, c.text, 1 - (c.embedding <=> query_embedding) as score,
         d.title, d.publisher, d.url, d.doc_date, d.tier, d.verified
  from reference_chunks c join reference_docs d on d.id = c.doc_id
  where c.embedding is not null
  order by c.embedding <=> query_embedding
  limit k $$;

alter table reference_docs   enable row level security;
alter table reference_chunks enable row level security;
