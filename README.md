# nn-news-agent — a newsroom engine with a deterministic ethics layer

## Quickstart (single process, half a day)
1. Create a Supabase project → SQL editor → run `supabase/quickstart.sql`.
2. `pip install -r requirements.txt` · `cp .env.example .env` and fill SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY, SLACK_WEBHOOK_URL (Slack → Apps → Incoming Webhooks → your editor channel).
3. `python run.py --seed` (beats + sources, embedded with Gemini) · `python run.py` (one pass) · check Slack.
4. Cron hourly: `0 * * * * cd /path/nn-news-agent && python run.py >> run.log 2>&1` — or `python run.py --loop`.
5. Optional: `python ethics/ingest_vvp.py` so memos cite the official clause text.
Everything else in this README (Edge Functions, worker, Ollama, email, Slack reactions) is the scale-up path; nothing in
quickstart mode has to be undone to get there.


One fixed pipeline, everything else is a plugin or a config file:

    load → draft → ethics screen → style check → memo → gate → (one revision) → render → deliver

The model drafts and writes the memo. The pipeline decides the sequence, runs the screens, and holds the gate.
Nothing here publishes; every product delivers to an editor.

## Layout
    core/         schema.py (typed records) · interfaces.py (7 plugin protocols) · pipeline.py · products.py · registry.py
                  archive.py + archive_site.py (item files and the bilingual index) · translate.py (English twins)
    plugins/      triggers/ loaders/ sources/ codes/ providers/ renderers/ deliverers/  — one file per implementation
    ethics/       server.py (MCP: screen_report, style_check, search_ethics, lookup_place …) · style.py · ingest_vvp.py · corpus/
    templates/    genre templates (regional_report.md, daily_digest.md, …)
    config/<newsroom>/   beats.json · place_names.json · supplements.json · products/*.json
    supabase/     migrations (001 core, 002 products/jobs/precedent) · functions/ingest (hourly RSS → embed → score → hits)
    worker/       app.py (FastAPI: /hit, /run/{product}, /products, /slack/reaction) · seed.py · Dockerfile
    eval/         dry_run.py (whole pipeline, no keys) — put the regression set here

## A product
`config/nord-norge/products/` ships three products: `regional-monitor` (hit → Slack), `daily-digest` (cron → email + Slack), `document-story` (press release / public document → Slack + email). A product names
its trigger, loader, template, ethics code + genre overlay, provider, renderer and deliverers. Four fields are not
per-product options and the loader refuses a file that sets them otherwise: `gate_required`, `memo_required`,
`ai_marking_required`, `publishes: false`.

To add a news type: write `templates/<genre>.md`, add a genre overlay in `plugins/codes/vvp.py` if the ethics weighting
differs, and drop a product JSON in the newsroom's folder. To add a newsroom: new `config/<id>/` folder. To add a source,
deliverer, or model: one file in `plugins/`.

## Models
`plugins/providers/` has `anthropic`, `gemini`, `ollama`, and `fake`. A product sets `"provider": "gemini"` or splits by stage:
`{"draft": "gemini", "memo": "anthropic"}`. Both models are recorded in `reports.versions`. Neither model is given tools; the
pipeline owns the sequence regardless of provider.

## Embeddings and Ollama
`EMBEDDER=local` additionally needs `pip install sentence-transformers` (kept out of requirements.txt so
deployments do not pull ~2GB of PyTorch for a lazily-imported path).
`core/embeddings.py` is the single embedding function; `EMBEDDER=ollama|gemini|local` (default ollama → bge-m3, 1024-d,
multilingual). Ingest, seed, related-item search and precedent all go through it. If EMBEDDER is not `local`, the Edge
Function only fetches raw items and `worker/embed_and_score.py` (run next to Ollama, `LOOP=1`) embeds and scores.
Switching embedder: run migration 003 with the right width, re-seed, re-embed.

Ollama models: `ollama pull bge-m3` (embeddings), `ollama pull gemma3:12b` (drafting; try a NorwAI/NorMistral GGUF for
better Norwegian). Product: `"provider": {"draft": "ollama", "memo": "anthropic"}`. Keep the memo on a hosted model.

## Parallel English (2026-09-15)

Every surface carries both languages at once. The source text stays canonical everywhere -- it is
what the beats are embedded against and what the ethics and style screens read -- and English is
added beside it, never instead of it.

| Surface | Norwegian (canonical) | English |
| --- | --- | --- |
| `items` row | `title`, `body` | `title_en`, `body_en`, detected `lang` |
| archived `.md` | front matter + body | `title_en:` in front matter, twin below the `<!-- en -->` mark |
| `archive/index.html` | right column | left column, plus all page chrome |
| products | `body` (Bokmal) | `sections.body_en`, `sections.headline_en` |
| email | subject, first half | subject after ` / `, `## English` section |

`core/translate.py` does the item half, batched by input characters rather than item count:
bodies run from a headline to enrich's 8000-char cap, and a fixed batch of N long items overruns
the provider's `max_output_tokens` and comes back as truncated JSON. It never raises -- a failed
batch leaves `title_en` null and the next pass picks it up.

    python run.py --translate     # drain the backlog, then rewrite every archive file
    TRANSLATE=0                   # switch translation off
    TRANSLATE_BODY_CHARS=8000     # per-item body cap (matches enrich's own cap)

Measured on 1074 items / 1.68M chars: a full backfill is about $1.20 on gemini-2.5-flash, a
normal day of ~350 items about $0.38.

**The English half of a report is not screened.** `plugins/codes/vvp.py` passes `draft.body` and
`draft.headline` to `screen_report()` and `style_check()`; `sections` is never passed. The gate is
therefore set entirely by the Norwegian, on the assumption that a faithful translation carries the
same material. That assumption is the reason the templates forbid adding anything in translation.

## Whose journalism the digest leads on (2026-09-16)

This desk is NRK's, so NRK's own reporting is context rather than the product — the editor has
already seen it. What earns the brief is what *other* outlets carry that bears on Norway.

`core/outlets.py` classifies each source as `own` (host under `nrk.no`) or `external`. It is
derived from the URL host rather than stored in a new column on purpose: `sources.json` is a
superset of the database, so a new column has to be merged into both by hand and a source added to
one and not the other classifies wrong in silence. Override a single source with
`sources.config.own`, which is already jsonb — no migration.

`WindowLoader` attaches `source` (the outlet's name) and `own` to every item, plus
`meta.external_count` / `meta.own_count`. Before this the drafter received only a `source_id`
integer and was inferring the outlet from the URL host.

`templates/daily_digest.md` therefore leads on `### Utenfor NRK`, demotes NRK to a bare-listing
`### NRK har allerede` (one line each, no analysis, so the editor can avoid commissioning a
duplicate), forbids an `own` item as the `Hovedsak` while any usable external item exists, and
requires «Ingen saker utenfor NRK i vinduet.» rather than padding a thin day. Measured on a 7-day
window: 18 external against 7 NRK, with the FOT-rutene story carried by both NRK Nordland and
Altaposten — the overlap case the template's last rule covers.

## The archive as a web site (2026-09-17)

An Eleventy build over the markdown archive: one page per item, both languages side by side, plus
outlet / source / day indexes. Served at:

    https://nn-news-agent.fly.dev/archive        HTTP Basic, user `redaksjonen`

    python run.py --publish     # build, tar, upload  (~2470 pages, ~3.6MB gzipped)
    ARCHIVE_PUBLISH=1           # also publish from sync_archive(); off by default

    site/                       config, templates, data layer  (in the repo)
    ~/.nn-news-site/            node_modules and build output  (NOT in the repo)

**The toolchain lives off the drive.** `node_modules` is ~130 packages of thousands of files, and
the repo is on a shared Google Drive where that syncs to everyone — the same reason the venv and
`.env` live under `~/.venvs` and `~/.config`. Install it once:

    npm install --prefix ~/.nn-news-site

`site/_data/items.js` reads the archive with **no YAML dependency**: `core/archive.py` writes front
matter as strict `key: <json-string>` lines, and a JSON double-quoted string is also a valid YAML
scalar, so `JSON.parse` per line is exact. (That quoting is why the archive is parseable at all —
Norwegian headlines are full of colons, and unquoted they read as nested mappings.) The config is
dependency-free for the same reason: Node would resolve a `require` there against the drive, where
there is no `node_modules`.

**The whole site travels as one tar.gz.** ~2500 files would be thousands of Storage calls per
publish; one object is also atomic, so a half-uploaded tree can never be served. The worker
unpacks it to a temp dir and re-checks the object's version at most once a minute.

**Why a Fly route rather than a Supabase link.** A signed URL cannot render HTML: Storage returns
signed objects as `text/plain` with `X-Content-Type-Options: nosniff` whatever their stored type,
because the token's scope is `download`. The only rendering route is `/object/public/`, which needs
a public bucket — and the archive holds near-complete article text from other newsrooms plus
translations of it, so public is the wrong answer. `/archive` reads the object with the
service-role key and serves it behind Basic auth, so the bucket stays private. Basic rather than
`?key=` because a secret in a URL lands in history, referrers and proxy logs.

The machine scales to zero, so the first load after an idle period takes a few seconds.

## The digest as the front page (2026-09-26)

Until now the digest was only ever an email. The site's front page was a list of sixteen category
names, and the one artefact the pipeline exists to produce — what happened, in order of importance,
with links — lived in an inbox. That is inverted: **the front page is the latest brief, in full, in
both languages**, followed by every story it rests on as a card with the outlet's name, our claim
about it, and a link to the original. The archive is one click away, which is the right
relationship: the brief is the product, the archive is the evidence.

    core/reports_export.py   ->  archive/reports.json    digests + the articles they cite
    site/_data/reports.js        parses it, renders the markdown body, joins to the archive
    site/_includes/digest.njk    one digest; one story card
    site/index.njk               latest brief + earlier briefs + category strip
    site/digest.njk              a page per brief, /digest/<date>-<product>-<id>/
    site/digests.njk             all briefs, by desk
    site/categories.njk          what index.njk used to be

The digest slug carries the row id because `<date>-<product>` **collides**: 2026-09-17 has two
daily digests (04:01 and 15:09, twelve claims and seventeen, different leads) and 2026-09-15 has
three. They are distinct briefs, not revisions, and Eleventy refuses to let two templates write one
file — which is how that surfaced.

### Two builds, one source tree

This is the part that matters. There are now two outputs and they are not interchangeable:

| | contents | pages | where it may go |
|---|---|---|---|
| **internal** (default) | whole archive: every item, its machine translation, category / outlet / day / source indexes | 7,703 | behind a password, or opened off the drive |
| **public** (`SITE_PUBLIC=1`) | the briefs only: our summary sentences, the source's headline, the outlet, a link to the original | 15 | a public URL |

    python run.py --public              # build the hostable subset       (~2s)
    python run.py --serve --public      # read it at http://127.0.0.1:8787
    python run.py --offline             # whole archive onto the drive    (~95s + copy)
    python run.py --serve               # read the internal build locally

**Why the split exists.** 1,902 of 7,589 archived items carry over 1,500 characters of another
newsroom's reporting, and the English column is a machine translation of it — a derivative work.
Internally that is an ordinary research archive; on an open URL it is an unlicensed mirror. The
briefs are the opposite: our own sentences, the source's headline, attribution, and a link out.

`eleventy.config.js` **drops the archive templates entirely** in public mode rather than hiding
their links, so there is no route to reach them and no orphaned files in the output. Then
`core/publish.py:_assert_no_archive()` refuses to hand back a public build that contains an archive
directory anyway. Belt and braces on purpose: the exclusion is one environment variable away from
being wrong, and the failure mode is not a broken page, it is 1,900 articles of someone else's text
on an open URL — the kind of mistake you hear about from someone else.

### Browsing the briefs by category

    site/_data/desks.js    the newsrooms, in order -- the one canonical copy
    site/_data/topics.js   the briefs' cited stories, grouped by beat
    site/topics.njk        /topics/        the categories
    site/topic.njk         /topic/<key>/   one category's stories, strongest match first
    site/404.njk           /404.html

`/topic/` is **not** `/category/`, and the difference is the whole reason both exist:

| | source | shows | builds |
|---|---|---|---|
| `/category/` | every scored hit in the archive | the source's own text | internal only |
| `/topic/` | only stories a brief cited | our claim + a link out | both |

They share a key (`<newsroom>-<beat>`, built identically in `core/reports_export.py` and
`site/_data/categories.js`), so a category means one thing across both surfaces. 105 of 109 cited
stories carry a beat; the four that do not were cited from outside the scored window.

A story cited by several briefs appears once, under the most recent, with every citing brief listed
on the card — otherwise the FOT-rutene airport story, which ran in four briefs, would fill its
category with copies of itself.

### Satire

    site/satire.njk        /satire/

The satire desk's briefs: jokes anchored to something a named politician on the Norwegian right
actually said, quoted with a URL. **Only briefs with `editor_decision = 'approved'` appear.** That
is not extra caution — `templates/satire_desk.md` states "Nothing here is published. The editor
chooses what, if anything, runs." The approval mechanism already existed (`reports.editor_decision`,
set from the review page), so the section is wired to it rather than around it. Approve one and it
appears on the next build.

The desk's window went from 24 hours to **4,392 (183 days)** on 2026-09-27. Its strongest mechanism
is `gapet` — they said X and did Y, both on the record — and a one-day window can essentially never
see both ends of that gap. `max_items` is unchanged at 40 but now means the top 40 by score across
the period rather than across yesterday. Caveat until roughly March 2027: ingest began 2026-09-14
and feeds carry only recent items, so the window currently reaches ~13 days of real material.

### Publishing

    python run.py --deploy      # build the public site and push it to Cloudflare Pages

Live at **https://norway-royal-news.pages.dev/**, `noindex` by decision — a real URL anyone with
the link can read, not an indexed product. `draft_local.cmd` runs `--deploy` after a successful
draft, so the site updates when a brief is written; it is not hooked to the hourly ingest, which
would be ~720 deploys a month to pick up trickling translations.

**Read this before touching the deploy.** On 2026-09-27 `wrangler pages project create` was run
from the toolchain directory. wrangler 4.142 "autoconfig" silently rewrites that command into
`wrangler deploy`, writing a `wrangler.jsonc` whose `assets.directory` it guesses from the current
directory — it guessed `_site`, and published 7,718 pages of the internal archive as a Worker. It
was deleted minutes later, but `_assert_no_archive()` never ran, because nothing went through this
code. Three things now stand between that and a repeat:

1. `deploy()` runs wrangler with **cwd = PUBLIC_DIR**, so the only directory autoconfig can guess
   is the one already checked.
2. `_no_stray_config()` deletes and hard-fails on any config wrangler generates during a deploy —
   left in place, such a file arms the *next* bare `wrangler` run.
3. `_assert_no_archive()` runs on the built tree and again on the exact bytes being uploaded.

There is deliberately no flag to deploy the internal build.

`--public` still uploads nothing on its own: where this gets served is an editorial decision about
publishing summaries under a masthead, not a build step.

## Approving drafts (2026-09-28)

    worker-review/              a Cloudflare Worker: the editor's queue
    supabase/functions/review/  the JSON API it reads (service-role key stays here)

    cd worker-review && wrangler deploy

The page lists every report with `editor_decision IS NULL`, in both languages, with its ethics
flags and every claim linked to its source, and Approve / Needs revision / Kill. The access link is
in `~/.config/nn-news-agent/review-url.txt` — off the shared Drive, like the venv and `.env`.

**Why a Worker and not the Apps Script it replaced.** The Apps Script was chosen when the only
options were this Edge Function, which cannot serve a page (Supabase wraps every response in
`default-src 'none'; sandbox` with `text/plain`, so a browser shows source), and the Fly worker,
whose trial had lapsed. Both constraints are gone. The decisive difference is deployment: an Apps
Script can only be updated by pasting code into a browser, which is exactly why it sat undeployed
for a day with `app_log` empty and 0 of 15 reports decided. `site/apps-script/` is deleted; there
is one review surface, not two.

**Auth, and why it is done twice.** Two ways in, and the Worker is never open on either:

1. **Cloudflare Access**, once `ACCESS_TEAM` and `ACCESS_AUD` are set in `wrangler.jsonc`. The
   assertion is verified *in the Worker* — signature against the team JWKS, `exp`, `iss`, and the
   audience of this application specifically. Not merely trusted from the edge: an Access
   application is bound to a hostname, and this Worker also answers on its `workers.dev` URL,
   which such a policy does not cover. Verifying here closes that bypass. Configuring Access needs
   a Cloudflare zone and a Zero Trust scope this machine's token does not have (`zone (read)`
   only), so it is a dashboard step.
2. **A cookie session**, until then. Visiting once with `?k=<REVIEW_KEY>` sets an HttpOnly, Secure,
   SameSite=Lax cookie and 303s to the bare path, so the key never settles in history, bookmarks or
   referrers. The cookie holds a hash of the key, not the key.

With neither configured the Worker returns 403 rather than rendering — it shows unpublished drafts
and can kill them, so failing open is not an option. Verified: 403 with no secrets set, 403 on a
wrong key, 200 with the cookie.

**Approving does not yet gate delivery.** `outbox` has 16 rows and 0 held, so every brief has been
emailed regardless of gate, including the six marked `blocked`. `editor_decision` currently only
controls what appears in `/satire/`. Switching holding on is a separate step, and it should happen
*after* this page is confirmed in daily use — otherwise blocked briefs pile up with no way out.

## Run
    pip install -r requirements.txt
    PYTHONPATH=. python eval/dry_run.py                 # no network
    python ethics/ingest_vvp.py                          # load official VVP text
    python worker/seed.py                                # beats + sources → Supabase
    uvicorn worker.app:app --port 8080                   # env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, GEMINI_MODEL, SLACK_WEBHOOK_URL, WEBHOOK_SECRET
    # Supabase Database Webhook: hits INSERT → POST /hit ; cron → POST /run/daily-digest ; POST /document {"product_id":"document-story","path"|"url"}
    # Slack Events API → POST /slack/reaction (reaction_added, message.channels); env SLACK_SIGNING_SECRET, SLACK_BOT_TOKEN
    # supabase functions deploy send-outbox (RESEND_API_KEY, MAIL_FROM) — schedule every 5 min

MCP server for use from Claude/other agents: `python ethics/server.py`.

## Newsroom: rikspolitikk (satire desk)

A second newsroom, `config/rikspolitikk`, running one product: `satire-desk`. It surveys national
political coverage and drafts jokes about the Norwegian political right for a human editor. Same
pipeline, same gate, same non-negotiables — it publishes nothing.

    PYTHONPATH=. PYTHONIOENCODING=utf-8 NEWSROOM_CONFIG=config/rikspolitikk \
      python eval/dry_run_satire.py                      # no network: proves the gate sorts jokes
    NEWSROOM_ID=rikspolitikk NEWSROOM_CONFIG=config/rikspolitikk python run.py --seed
    NEWSROOM_ID=rikspolitikk PRODUCT=satire-desk NEWSROOM_CONFIG=config/rikspolitikk python run.py

PowerShell has no inline env-var prefix, so on the Windows box the same three are:

    $env:NEWSROOM_ID='rikspolitikk'; $env:NEWSROOM_CONFIG='config/rikspolitikk'; $env:PYTHONIOENCODING='utf-8'; $env:PYTHONPATH='.'
    & "$HOME\.venvs\nn-news-agent\Scripts\python.exe" eval/dry_run_satire.py
    & "$HOME\.venvs\nn-news-agent\Scripts\python.exe" run.py --seed
    $env:PRODUCT='satire-desk'; & "$HOME\.venvs\nn-news-agent\Scripts\python.exe" run.py

Call that interpreter by full path rather than a bare `python`: the venv is off the shared drive and
carries the `truststore` hook this machine needs, and without it every HTTPS fetch fails
certificate verification in a way that looks like a dead feed.

Three things about it are deliberate and worth not undoing by accident:

- **Beats are organised by contradiction type, not by policy area.** `lovnad-mot-levering`,
  `avgift-og-lommebok`, `retorikk-og-utspill` and so on score items for the gap between a stated
  position and an outcome, because that gap is what satire runs on. A beat organised as
  "immigration" returns items that are mostly just sad.
- **`max_revisions` is 0**, unlike the news products. Two of the screens raised for this genre are
  topic detectors — `ethnicity_or_identity` matches «asyl»/«innvandr-», `accusation_requires_reply`
  matches «kritiser-» — so they fire on the subject rather than on any abuse of it, and an automatic
  redraft cannot clear them without abandoning the subject. It would only sand off the concrete
  detail that made the joke work. Blocked drafts are delivered anyway; the editor is the corrector.
- **National scope only, by decision (2026-09-14).** The desk covers political comments and activities
  at national level and shares no beats or sources with `nord-norge`. Pulling the northern dimension in
  — Fosen and wind power, district policy, fisheries quotas, Helse Nord — was considered and declined;
  the two newsrooms stay separate. A Finnmark story reaches this desk only if a national outlet covers
  it. Don't wire the regional feeds in without asking.
- **`body` carries only what could run; editor-only matter lives in `sections`.** The ethics screen and
  the style check read `body` and nothing else, so anything put there is judged as if it were being
  published. Rejected-material notes are not being published, and keeping them in `body` made the desk
  fail its own screen for showing its work — a run was gated `blocked` under VVP 4.7 because
  «straffesak» appeared in a line explaining why a court case had been *rejected* as out of remit.
  `ikke_brukt` and `til_redaktoren` are now sections (the renderer pairs any `x` with `x_en`), which
  moved a live run from `blocked` to `review` while still putting the notes in front of the editor.
- **Every joke carries its basis.** The template requires a `Grunnlag:` line with the quoted fact
  and the URL, kept visually separate from the joke, so the editor can check one against the other.
  This is a comedy requirement before it is an ethics one: the specificity is the joke, and a desk
  that stops sourcing starts producing insults with a name attached.

Known gap: **FrP publishes no RSS feed** (`/feed`, `/rss`, `/rss.xml`, `/aktuelt/rss` all 404 as of
2026-09-14), so the primary target party's own on-the-record output is not ingestible and reaches
the desk only through third-party reporting. Regjeringen.no is 403 to `httpx` but loads in a
browser — a User-Agent problem, not a missing feed, and worth retrying. See `sources.json` notes.

## What runs where (2026-09-14)

The pipeline is split across three surfaces, and the split is not obvious from the code:

| Surface | Job | Embeds? | Scheduled by |
|---|---|---|---|
| Fly `nn-news-agent` | drafting: `/run/{product}`, `/hit`, `/document` | **no** | pg_cron → digest 06:00, satire 15:00 Europe/Oslo |
| Fly `send-outbox` | email delivery | no | pg_cron every 5 min |
| This Windows machine | ingest: `run.py --ingest` (fetch + score) | **yes**, bge-m3 via local Ollama | Task Scheduler, hourly |

**The drafting worker never embeds.** Verified by import: `core.embeddings` is not reachable from
`worker.app` even with every plugin loaded. `EMBEDDER`/`EMBED_DIM` in `fly.toml` are vestigial.
That is why drafting runs happily on a 512MB machine that boots in a second, and why the `/ingest`
route imports `run` lazily — an embedder misconfiguration must not be able to stop drafting.

**Ingest is pinned to this machine** because embedding is bge-m3 over Ollama at `localhost:11434`.
`embedder/fly.toml` holds the recipe for moving it to a private Fly service (`OLLAMA_URL` is already
an env var, so it is config, not code). That is blocked on the Fly org being a trial: creating a
release for a second app needs a card on file. Until then `run.py --ingest` on the hourly task is
what keeps hits fresh, and **if this machine is asleep the cron-driven desks draft from stale hits
without saying so.**

`--ingest` deliberately does not draft. `report()` marks each hit it uses as `reported`, so a local
pass that drafted would consume the day's hits before the scheduled desk loaded its window, and
deliver a second copy of every report.

## Screening change, 2026-09-14 (affects both newsrooms)

`ethics/server.py`'s `ethnicity_or_identity` pattern began `sam\w*`, which matched **samtidig, samme,
sammen, samarbeid, samfunn, samlet, samferdsel, samordning** — ordinary Norwegian. VVP 4.3 therefore
fired on nearly every report in both newsrooms and the flag carried no information. It now enumerates
actual Sámi terms (`sámi|sápmi|samisk|samer|samene|sameting|samerett|…`), and `russ\w*` — which matched
russ, russetid and russebuss, i.e. Norwegian graduation rather than nationality — became
`russisk|russer|russland`. Genuine hits (`samisk`, `samer`, `Sametinget`, `innvandring`, `asylpolitikk`,
`russisk`) are unaffected; `eval/dry_run.py` is unchanged. Expect **fewer** VVP 4.3 flags on Nord-Norge
reports from this date, and treat the ones that remain as meaningful.

## Roadmap
1 deploy · 2 load VVP text and verify RSS/place names · 3 events beat · 4 multilingual embedder + threshold tuning ·
5 precedent retrieval into the memo (table + writer are done) · 6 PFU rulings ingest with fact-pattern annotation ·
7 Etikkhåndboka per-clause comments · 8 newsroom KI policy document · 9 regression set in eval/
