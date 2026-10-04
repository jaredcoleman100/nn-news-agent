"""Single-process mode: fetch → embed → score → draft → screen → memo → Slack, one pass. Run hourly by cron.

    cp .env.example .env   # fill in 4 keys
    python run.py          # one pass;  python run.py --seed  first time;  python run.py --loop  to poll forever

Uses the same core/ and plugins/ as the full deployment; only the entrypoint differs.
"""
from __future__ import annotations
import argparse, json, os, sys, time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # pip install python-dotenv
load_dotenv(ROOT / ".env")
load_dotenv(Path.home() / ".config" / "nn-news-agent" / ".env")  # fallback: keys off the shared drive

# AFTER load_dotenv on purpose. setdefault writes into os.environ, and load_dotenv does not
# override what is already there, so setting these first made EMBEDDER and EMBED_DIM in .env
# silently unreachable — you could not switch embedder from config at all. These are fallbacks.
os.environ.setdefault("EMBEDDER", "gemini")
os.environ.setdefault("EMBED_DIM", "768")

from core import archive, archive_site, enrich, outlets, pipeline, publish as publish_mod, registry, reports_export, translate
from core.embeddings import embed
from core.products import list_newsrooms, load_product, resolve_product
from core.schema import Job, Report
from plugins.loaders.db import sb

NEWSROOM = os.environ.get("NEWSROOM_ID", "nord-norge")
PRODUCT = os.environ.get("PRODUCT", "regional-monitor")
# The archive is a tree of files under archive/, written during fetch. On a Fly machine that
# filesystem is ephemeral, so writing there costs work and keeps nothing. It is also a DERIVED
# artifact -- sync_archive() rebuilds every file from `items` -- so cloud ingest sets
# ARCHIVE_WRITES=0 and the durable copy is rebuilt wherever the archive actually lives.
ARCHIVE_WRITES = os.environ.get("ARCHIVE_WRITES", "1") != "0"
registry.load_all()


def _source_ids() -> list[str]:
    """Source ids owned by this newsroom.

    `sources`, `beats` and `hits` carry a `newsroom_id`; `items` does not. An item therefore
    belongs to a newsroom only through the source that produced it, which makes source ownership
    the one honest way to decide whose beats may claim an item. Every newsroom-scoped read goes
    through here.

    Without this, a second newsroom silently corrupts the first: `match_beats` ranks against every
    active beat regardless of owner, so a run stamps whatever `NEWSROOM_ID` it happens to hold onto
    hits belonging to the other newsroom's beats — and because `items.embedding` is the
    already-scored sentinel, the newsroom that runs second skips those items forever.
    """
    return [s["id"] for s in sb().table("sources").select("id").eq("newsroom_id", NEWSROOM).execute().data]


# ---------------------------------------------------------------- seed
def _columns(src: dict) -> dict:
    """Drop config-file-only keys before writing a source row.

    `sources.json` is documentation as much as configuration -- entries carry `_note` explaining
    why a feed was withdrawn, `_window_hours_note`, and so on. Those are not columns, and
    PostgREST rejects the whole upsert with "Could not find the '_note' column" when one is
    present. Underscore prefix is the convention for "for the reader, not the database".
    """
    return {k: v for k, v in src.items() if not k.startswith("_")}


def seed() -> None:
    beats = json.loads((ROOT / "config" / NEWSROOM / "beats.json").read_text(encoding="utf-8"))["beats"]
    vecs = embed([b["description"] + " " + " ".join(b["keywords_nb"] + b["keywords_en"]) for b in beats])
    for b, v in zip(beats, vecs):
        # `threshold` is written only when the newsroom's beats.json states one, so each desk pins
        # its own. The column default cannot be correct for both: nord-norge measured 0.48 against
        # its own score distribution and rikspolitikk 0.50 against its own, and a beat created
        # without an explicit value silently inherits whichever number the other desk last set.
        # See supabase/SHARED-DATABASE.md.
        row = {"id": b["id"], "name": b["name"], "description": b["description"],
               "keywords": b["keywords_nb"] + b["keywords_en"], "ethics_profile": b["ethics_profile"],
               "embedding": v, "newsroom_id": NEWSROOM}
        if b.get("threshold") is not None:
            row["threshold"] = b["threshold"]
        sb().table("beats").upsert(row).execute()
    srcs = json.loads((ROOT / "config" / NEWSROOM / "sources.json").read_text(encoding="utf-8"))
    for s in srcs:
        sb().table("sources").upsert({**_columns(s), "newsroom_id": NEWSROOM},
                                     on_conflict="url").execute()
    print(f"seeded {len(beats)} beats, {len(srcs)} sources")


# ---------------------------------------------------------------- fetch
def _parse_dt(text: str) -> datetime | None:
    """Parse a feed date. RFC-822 first, then ISO.

    No dateutil: it is not a dependency here, and feeds in practice emit one of these two --
    "Mon, 28 Sep 2026 10:00:00 GMT" from RSS, and ISO-8601 from sitemaps and the database.
    """
    for parse in (parsedate_to_datetime, datetime.fromisoformat):
        try:
            return parse(text)
        except (ValueError, TypeError, OverflowError):
            continue
    return None


def _published_floor(src: dict) -> str | None:
    """The oldest publication date this source may contribute, or None for no limit.

    Set per source as `config.min_published` (an ISO date). Only the topic-filtered query feeds
    use it: a Google News search returns whatever best matches the query, not what is recent, so
    89 of 100 items from the Indonesian feed and 57 of 100 from the English one were more than a
    month old, one of them from 2024. A daily monitoring desk should not be quietly absorbing an
    archive.

    Briefs were never at risk -- the window loader filters on published_at, so an old item cannot
    reach one. The damage was to the archive and the category pages, which rank by score and not
    by date, so a two-year-old piece could sit at the top of a category.

    Deliberately opt-in rather than a global cutoff: the scholarly adapters legitimately return
    decade-old papers, and Sivilombudet and SSB publish documents with old dates that still matter.
    """
    return ((src.get("config") or {}).get("min_published") or "").strip() or None


def _published_since(published_at: Any, floor: str) -> bool:
    """True when `published_at` is on or after `floor` (an ISO date).

    An item with NO date is KEPT. Feeds omit dates often enough that discarding those would
    silently drop live material -- and the failure this guards against is an archive arriving in
    bulk, which always carries dates.
    """
    if not published_at:
        return True
    got = _parse_dt(str(published_at))
    if got is None:
        return True                   # unparseable is not evidence of being old
    cutoff = datetime.fromisoformat(floor)
    if got.tzinfo is not None:
        cutoff = cutoff.replace(tzinfo=got.tzinfo)
    return got >= cutoff


def fetch() -> int:
    n = 0
    # Deliberately NOT newsroom-scoped, unlike score()/report(). Fetching is idempotent and an item
    # is owned by its source, so one pass can collect for every newsroom at once and whichever
    # newsroom runs next still sees only its own items through _source_ids(). Scoping this would
    # just mean each newsroom re-polls the same feeds on its own schedule.
    for src in sb().table("sources").select("*").eq("active", True).execute().data:
        try:
            adapter = registry.get("source", src.get("kind") or "rss")
            floor = _published_floor(src)
            for e in adapter.fetch(src, src.get("last_polled_at")):
                if not e.get("url"):
                    continue
                if floor and not _published_since(e.get("published_at"), floor):
                    continue          # older than this source's floor; see _published_floor()
                r = sb().table("items").upsert({"source_id": src["id"], **e}, on_conflict="source_id,url", ignore_duplicates=True).execute()
                rows = r.data or []
                n += len(rows)
                if not rows:
                    continue          # already had it; never refetch the article page
                got = enrich.article(e["url"], str(e.get("body") or ""), str(e.get("title") or ""))
                if got:               # feeds ship headlines; sitemaps ship only a URL and a date
                    e.update(got)
                    sb().table("items").update(got).eq("id", rows[0]["id"]).execute()
                if ARCHIVE_WRITES:
                    archive.save(e, src["name"], org=outlets.org_of(src))   # enriched text, not the headline
            sb().table("sources").update({"last_polled_at": "now()"}).eq("id", src["id"]).execute()
        except Exception as ex:  # noqa: BLE001
            print(f"  source {src['name']}: {ex}")
    return n


# ---------------------------------------------------------------- embed + score
def score() -> int:
    rows = sb().table("items").select("id,title,body,source_id").is_("embedding", "null").in_("source_id", _source_ids()).order("fetched_at").limit(64).execute().data
    if not rows:
        return 0
    vecs = embed([f"{r['title'] or ''}\n{(r['body'] or '')[:2000]}" for r in rows])
    # Scope to this newsroom: the beats table is shared with the rikspolitikk desk.
    th = {b["id"]: b["threshold"] for b in sb().table("beats").select("id,threshold")
          .eq("active", True).eq("newsroom_id", NEWSROOM).execute().data}
    cap = int(sb().table("config").select("value").eq("key", "max_beats_per_item").single().execute().data["value"])
    srcs = {x["id"]: x for x in sb().table("sources").select("id,beat_hint,config").execute().data}
    hits = 0
    for r, v in zip(rows, vecs):
        sb().table("items").update({"embedding": v}).eq("id", r["id"]).execute()
        matches = sb().rpc("match_beats", {"query_embedding": v, "newsroom": NEWSROOM}).execute().data
        src = srcs.get(r.get("source_id")) or {}
        hint = src.get("beat_hint")
        # A narrow, pre-vetted outlet (Barents Observer, SVT Sápmi) is an editorial judgement
        # already made, so the hint wins outright. This is what makes foreign-language sources
        # usable at all: Norwegian-embedded beats score ru/fi/en/de items 0.45-0.57, under any
        # sane threshold. The measured similarity is still recorded, so the memo stays honest.
        if hint and (src.get("config") or {}).get("trust_hint"):
            chosen = [{"beat_id": hint,
                       "score": next((m["score"] for m in matches if m["beat_id"] == hint), 0.0)}]
        else:
            over = [m for m in matches if m["score"] >= th.get(m["beat_id"], 1.0)]
            # Best-matching beats only: each hit becomes its own editor memo, so an unbounded
            # list mails the same story N times.
            chosen = sorted(over, key=lambda x: x["score"], reverse=True)[:cap]
        for m in chosen:
            sb().table("hits").upsert({"item_id": r["id"], "beat_id": m["beat_id"], "score": m["score"], "newsroom_id": NEWSROOM},
                                      on_conflict="item_id,beat_id", ignore_duplicates=True).execute()
            hits += 1
    return hits


# ---------------------------------------------------------------- report
def _store(r: Report) -> Report:
    job = sb().table("jobs").insert({"newsroom_id": r.job.newsroom_id, "product_id": r.job.product_id,
                                     "trigger": r.job.trigger, "payload": r.job.payload}).execute().data[0]
    r.job.id = job["id"]
    row = sb().table("reports").insert({**r.to_row(), "hit_id": r.job.payload.get("hit_id")}).execute().data[0]
    r.id = row["id"]
    sb().table("runs").insert({"job_id": job["id"], "report_id": r.id, "hit_id": r.job.payload.get("hit_id"), "status": "ok",
                               "finished_at": "now()", "steps": r.log, "input_tokens": r.usage["input"], "output_tokens": r.usage["output"]}).execute()
    return r


def oslo_hour() -> int:
    """Current hour in Europe/Oslo.

    The desks are scheduled in Oslo time but this machine runs on US Pacific, and the two regions
    change clocks on different dates -- the gap is 9 hours most of the year and 8 for the couple of
    weeks between the EU and US switchovers. A fixed local time therefore drifts an hour twice a
    year, which would silently draft against the wrong day's window. Schedule at BOTH candidate
    local hours and let this guard pick the right one, exactly as the pg_cron jobs do with
    `to_char(now() at time zone 'Europe/Oslo','HH24')`.

    Needs `tzdata`: Windows ships no tz database, so zoneinfo has nothing to read without it.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Europe/Oslo")).hour


def drafted_today(product_id: str, newsroom_id: str | None = None) -> bool:
    """Has this product already produced a report for the CURRENT Oslo date?

    The idempotency key for drafting. `created_at` is stored in UTC and the deadline is in Oslo
    time, so the comparison has to be done in Oslo time or it is wrong for the nine hours a day
    the two dates disagree -- a brief drafted at 23:30 Oslo is 21:30 UTC the same day, but one
    drafted at 00:30 Oslo is 22:30 UTC the day BEFORE, and a UTC-date check would draft it twice.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    oslo = ZoneInfo("Europe/Oslo")
    today = datetime.now(oslo).date()
    q = sb().table("reports").select("created_at").eq("product_id", product_id)
    if newsroom_id:
        q = q.eq("newsroom_id", newsroom_id)
    for row in q.order("created_at", desc=True).limit(10).execute().data:
        when = _parse_dt(row.get("created_at"))
        if not when:
            continue
        # A naive timestamp is UTC here (Postgres timestamptz, serialised without an offset by
        # some PostgREST versions). Saying so explicitly matters: astimezone() on a naive value
        # assumes the MACHINE's zone, which is US Pacific, and that is a nine-hour error -- enough
        # to put the report on the wrong Oslo date and draft a second brief for the same day.
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when.astimezone(oslo).date() == today:
            return True
    return False


def run_product(product_id: str, newsroom_id: str | None = None) -> int | None:
    """Draft one product now, exactly as the worker's POST /run/{product_id} does.

    Same four steps: resolve the product, build a Job through its declared trigger, run the
    pipeline, store and deliver. It lives here so scheduled drafting does not require the Fly
    worker -- and this machine is already non-optional, because embedding needs the local Ollama,
    so moving drafting here removes a dependency rather than adding a point of failure.

    Respects the `paused` config flag, like the worker's _guard().
    """
    if sb().table("config").select("value").eq("key", "paused").single().execute().data["value"]:
        print("paused")
        return None
    product = resolve_product(product_id, newsroom_id)
    job = registry.get("trigger", product["trigger"]).to_job(product, {})
    r = pipeline.run(job, product, store=_store)
    print(f"report #{r.id} [{r.gate}] {product['newsroom_id']}/{product['id']}: {r.draft.headline}")
    translate_cited(r.id)
    return r.id


def translate_nb_pass(limit: int = 0) -> int:
    """Give non-Norwegian items a Norwegian headline.

    Only items whose language is already known and is not nb/nn: `title` is the Norwegian text for
    a Norwegian source, so there is nothing to translate and writing title_nb would duplicate it.

    Newest first. With Chinese, Japanese, Arabic, Hindi, Indonesian, French, Spanish and German
    sources in the roster the site's Norwegian column would otherwise render Arabic script under a
    heading that says Kilde -- which is what prompted this pass.

    Never raises, for the same reason translate_pass() does not: the source text is stored and the
    beats score against it, so a translation outage must not stop ingest.
    """
    if not translate.ENABLED:
        return 0
    cap = limit or int(os.environ.get("TRANSLATE_ITEMS", "60"))
    rows = (sb().table("items").select("id,title")
            .is_("title_nb", "null").not_.is_("lang", "null")
            .not_.in_("lang", ["nb", "nn"])
            .order("fetched_at", desc=True).limit(cap).execute().data)
    if not rows:
        return 0
    done, usage = translate.translate(rows, titles_only=True, target="nb")
    for d in done:
        sb().table("items").update({"title_nb": d["title_nb"]}).eq("id", d["id"]).execute()
    print(f"translated {len(done)}/{len(rows)} titles to Norwegian "
          f"({usage['input']}+{usage['output']} tok)", flush=True)
    return len(done)


def translate_cited(report_id: int) -> int:
    """Translate the titles of the articles this report cites, right after drafting it.

    The hourly pass takes 60 untranslated items newest-first, which sounds like it would cover a
    fresh digest and does not: intake runs ahead of it, so the items a brief cites are routinely
    still untranslated hours later. Measured on report #13 -- all twelve cited articles had no
    `title_en`, fetched between 07:03 and 18:00 the day before it was drafted.

    That is invisible in an email and glaring on the front page, where every story card then reads
    "English not yet available" above a Norwegian headline. These are also the highest-value
    translations in the system: a dozen titles the editor will actually read, against sixty picked
    only for being recent. One model call, immediately after the brief exists.

    Never raises. A brief that is drafted and delivered is worth more than a bilingual one that is
    not, so a translation outage must not fail the run -- the same rule translate_pass() follows.
    """
    if not translate.ENABLED:
        return 0
    try:
        row = sb().table("reports").select("claims").eq("id", report_id).single().execute().data
        urls = sorted({(c or {}).get("source_url") for c in (row.get("claims") or [])} - {None, ""})
        if not urls:
            return 0
        # Chunked by URL LENGTH, not count: PostgREST puts `in_` values in the query string, and
        # aggregator links run to ~450 characters each, so a brief citing enough of them builds a
        # request the server rejects with a bare 400. See core/reports_export.py:_url_chunks.
        rows = [r for chunk in reports_export._url_chunks(urls)
                for r in sb().table("items").select("id,title")
                .in_("url", chunk).is_("title_en", "null").execute().data]
        if not rows:
            return 0
        done, usage = translate.translate(rows, titles_only=True)
        for d in done:
            sb().table("items").update({"lang": d["lang"], "title_en": d["title_en"]}) \
                .eq("id", d["id"]).execute()
        print(f"  cited titles: translated {len(done)}/{len(rows)} to English "
              f"({usage['input']}+{usage['output']} tok)", flush=True)

        # And Norwegian, for the cited stories that are not Norwegian to begin with. Same argument
        # as the English pass: these dozen headlines are the ones an editor will actually read, and
        # a card whose Norwegian column is in Mandarin is not bilingual.
        nb_rows = [r for chunk in reports_export._url_chunks(urls)
                   for r in sb().table("items").select("id,title")
                   .in_("url", chunk).is_("title_nb", "null")
                   .not_.is_("lang", "null").not_.in_("lang", ["nb", "nn"]).execute().data]
        if nb_rows:
            nb_done, nb_usage = translate.translate(nb_rows, titles_only=True, target="nb")
            for d in nb_done:
                sb().table("items").update({"title_nb": d["title_nb"]}).eq("id", d["id"]).execute()
            print(f"  cited titles: translated {len(nb_done)}/{len(nb_rows)} to Norwegian "
                  f"({nb_usage['input']}+{nb_usage['output']} tok)", flush=True)
        return len(done)
    except Exception as ex:  # noqa: BLE001
        print(f"  cited titles: translation skipped ({ex})", flush=True)
        return 0


def report() -> int:
    cap = int(sb().table("config").select("value").eq("key", "max_reports_per_run").single().execute().data["value"])
    hits = sb().table("hits").select("id,score,beat_id,item_id").eq("status", "new").eq("newsroom_id", NEWSROOM).order("score", desc=True).limit(cap).execute().data
    # A scholarly item must not be drafted with the news template, so the product is resolved
    # per hit: sources.config.product overrides, otherwise the newsroom default.
    routes, cache = {}, {}
    if hits:
        items = sb().table("items").select("id,source_id").in_("id", [h["item_id"] for h in hits]).execute().data
        item_src = {i["id"]: i.get("source_id") for i in items}
        for x in sb().table("sources").select("id,config").execute().data:
            routes[x["id"]] = (x.get("config") or {}).get("product")
    done = 0
    for h in hits:
        pid = routes.get(item_src.get(h.get("item_id"))) or PRODUCT
        if pid not in cache:
            cache[pid] = load_product(NEWSROOM, pid)
        product = cache[pid]
        sb().table("hits").update({"status": "processing"}).eq("id", h["id"]).execute()
        try:
            job = Job(product_id=product["id"], newsroom_id=NEWSROOM, trigger="hit", payload={"hit_id": h["id"]})
            r = pipeline.run(job, product, store=_store)
            sb().table("hits").update({"status": "reported"}).eq("id", h["id"]).execute()
            print(f"  report #{r.id} [{r.gate}] {r.draft.headline}")
            done += 1
        except Exception as ex:  # noqa: BLE001
            sb().table("hits").update({"status": "failed"}).eq("id", h["id"]).execute()
            sb().table("runs").insert({"hit_id": h["id"], "status": "error", "error": str(ex), "finished_at": "now()"}).execute()
            print(f"  hit {h['id']} failed: {ex}")
    return done


def sync_archive() -> None:
    """Rewrite every archive file from the database, then rebuild the index. The archive is only
    useful if it matches the rows, and enrichment changes bodies after the file was first written."""
    # Also deliberately global: the archive is one tree on disk keyed by source name and date, not
    # one tree per newsroom. Scoping this would leave the other newsroom's files stale against the
    # rows they are supposed to mirror, which is the one thing the archive must never be.
    srcs = {s["id"]: s for s in sb().table("sources").select("id,name,url,config").execute().data}
    names = {i: s["name"] for i, s in srcs.items()}
    # Paged, because PostgREST caps an unbounded select at 1000 rows and returns it without
    # complaint. Unpaged, this silently rewrote only the first 1000 items and left every item
    # beyond that stale against the rows it is supposed to mirror -- the one thing the archive
    # must never be. The cap was invisible until the table passed 1000.
    cols = "id,url,title,body,published_at,source_id,title_en,body_en,lang"
    rows, page, size = [], 0, 1000
    while True:
        got = sb().table("items").select(cols).order("id").range(page * size, page * size + size - 1).execute().data
        rows += got
        if len(got) < size:
            break
        page += 1
    keep = set()
    written = 0
    for r in rows:
        got = archive.save(r, names.get(r.get("source_id"), "unknown"), overwrite=True,
                           org=outlets.org_of(srcs.get(r.get("source_id"))))
        if got:
            keep.add(got.resolve())
            written += 1

    # Prune orphans. path_for() buckets by published_at, so when a feed revises that timestamp the
    # item lands in a different day directory and the old file is simply left behind -- 32 of them
    # had accumulated, stale since before the front matter was made valid YAML, and any generator
    # pointed at this tree would publish them as duplicate pages.
    #
    # Guarded: this pass rewrites every row, so anything left over is genuinely an orphan -- but
    # only if the pass actually succeeded. If it wrote implausibly few files (a truncated select, a
    # read-only archive) pruning would delete the archive instead of tidying it, so bail out loudly.
    on_disk = {p.resolve() for p in archive.ARCHIVE_DIR.rglob("*.md")}
    orphans = on_disk - keep
    if orphans and written < len(on_disk) * 0.5:
        print(f"archive: NOT pruning {len(orphans)} orphans - only {written} of {len(on_disk)} "
              f"files were rewritten, which looks like a failed pass rather than a tidy-up")
    else:
        for o in orphans:
            try:
                o.unlink()
            except OSError as e:
                print(f"  archive: could not remove orphan {o.name}: {e}")
        if orphans:
            print(f"archive: pruned {len(orphans)} orphaned files")
    site = archive_site.build()
    print(f"archive: rewrote {written} of {len(rows)} files" + (f"; index -> {site}" if site else ""))
    if os.environ.get("ARCHIVE_PUBLISH", "0") == "1":
        # Off by default: the hourly ingest should not push a 4MB object every hour for the sake
        # of a handful of new items. Turn it on where the hosted copy is the one people read.
        try:
            publish_mod.publish(sb())
        except Exception as ex:  # noqa: BLE001
            print(f"  publish failed (archive on disk is unaffected): {ex}")


def backfill() -> None:
    """Fill in bodies for items the feed delivered as headlines, then re-embed and re-score them.
    Existing embeddings and hits were derived from a title alone, so both are discarded."""
    rows = sb().table("items").select("id,url,title,body").in_("source_id", _source_ids()).execute().data
    thin = [r for r in rows if len(str(r.get("body") or "")) < enrich.MIN_BODY]
    print(f"{len(thin)} of {len(rows)} items have a body under {enrich.MIN_BODY} chars")
    filled = 0
    for r in thin:
        got = enrich.article(r["url"], str(r.get("body") or ""), str(r.get("title") or ""))
        if not got.get("body"):
            continue
        sb().table("items").update({**got, "embedding": None}).eq("id", r["id"]).execute()
        sb().table("hits").delete().eq("item_id", r["id"]).execute()   # scored from a headline
        filled += 1
    print(f"enriched {filled} items; re-embedding and re-scoring")
    total = 0
    for _ in range(20):                      # score() handles 64 items per call
        if not sb().table("items").select("id").is_("embedding", "null").in_("source_id", _source_ids()).limit(1).execute().data:
            break
        total += score()
    print(f"{total} hits after re-score")
    sync_archive()


def translate_pass(limit: int = 0, shortest_first: bool = False, titles_only: bool = False) -> int:
    """Give untranslated items their English twin, newest first.

    Deliberately NOT newsroom-scoped, for the same reason fetch() is not: an item belongs to its
    source, and an English rendering is a property of the item, not of the desk reading it. One
    pass serves both desks. Newest first because the freshest items are the ones the morning
    digest and the archive index are about to display; the backlog drains behind them.

    Never raises. The source text is already stored and is what the beats score against, so a
    translation outage must not be able to stop ingest.
    """
    if not translate.ENABLED:
        return 0
    # 60, not "everything": this runs inside the hourly Task Scheduler job, and 60 items is about
    # five model calls -- roughly ten minutes at the measured rate, against a one-hour period. A
    # backlog therefore drains over several hours instead of one pass overrunning the next.
    cap = limit or int(os.environ.get("TRANSLATE_ITEMS", "60"))
    if titles_only:
        q = sb().table("items").select("id,title").is_("title_en", "null")
    else:
        # Bodies for items whose title is already done. Skipping empty bodies matters: they would
        # otherwise be selected forever, since a blank body can never produce a body_en.
        q = (sb().table("items").select("id,title,body")
             .not_.is_("title_en", "null").is_("body_en", "null").neq("body", ""))
    # Newest first for the hourly pass: those are the items the morning digest and the index are
    # about to display. A backfill wants the opposite -- item length is heavily skewed (759 of
    # 1098 under 985 chars, but 86 sitting exactly at enrich's 8000 cap), and newest-first
    # front-loads the expensive ones, so draining by length clears most of the archive far sooner.
    # PostgREST cannot order by an expression, so order by the body column itself: shorter strings
    # sort first, which is the property wanted here.
    q = q.order("body", desc=False) if shortest_first else q.order("fetched_at", desc=True)
    rows = q.limit(cap).execute().data
    if not rows:
        return 0
    done, usage = translate.translate(rows, titles_only=titles_only)
    for d in done:
        patch = {"lang": d["lang"], "title_en": d["title_en"]}
        if "body_en" in d:
            patch["body_en"] = d["body_en"]
        sb().table("items").update(patch).eq("id", d["id"]).execute()
    print(f"translated {len(done)}/{len(rows)} {'titles' if titles_only else 'items'} "
          f"({usage['input']}+{usage['output']} tok)", flush=True)
    return len(done)


def ingest_pass() -> None:
    """Fetch and score for every newsroom, and nothing else.

    Drafting is scheduled separately (pg_cron -> the Fly worker: daily-digest 06:00, satire-desk
    15:00 Oslo). A machine whose job is keeping hits fresh must therefore NOT draft: report() marks
    each hit it uses as `reported`, so a local pass that drafted would consume the day's hits before
    the scheduled desk ever loaded its window, and deliver a second copy of every report besides.

    This is the local stand-in for the worker's /ingest route, for as long as embedding needs the
    Ollama on this machine. The two do the same work and must keep doing the same work.
    """
    global NEWSROOM
    print(f"fetched {fetch()} new items", flush=True)
    for nr in list_newsrooms():
        NEWSROOM = nr                       # read by _source_ids() and score()
        ids = _source_ids()
        hits = 0
        for _ in range(int(os.environ.get("SCORE_BATCHES", "12"))):
            if not sb().table("items").select("id").is_("embedding", "null") \
                     .in_("source_id", ids).limit(1).execute().data:
                break
            hits += score()
        print(f"  {nr}: {hits} new hits", flush=True)
    # Titles first, bodies only once every title is done. A title is ~60 characters, so one request
    # carries ~40 of them against ~5 items when bodies are included: on the free Gemini tier
    # (20 requests/day/model) titles keep pace with ingest and bodies cannot. The title is also what
    # the archive index, the category pages and the card blurbs actually show.
    if translate_pass(titles_only=True) == 0:
        translate_pass()
    # After English, because a Norwegian headline is only wanted for items whose language
    # the English pass has already detected -- translate_nb_pass filters on lang not null.
    translate_nb_pass()


def one_pass() -> None:
    if sb().table("config").select("value").eq("key", "paused").single().execute().data["value"]:
        print("paused"); return
    print(f"fetched {fetch()} new items")
    # score() embeds 64 items per call. With 27 sources a single pass can land several hundred
    # items, so one call per pass never catches up; drain the backlog instead. Embedding the
    # whole 736-item backlog costs about $0.07, so the bound is generosity, not thrift.
    hits, batches = 0, int(os.environ.get("SCORE_BATCHES", "12"))
    for _ in range(batches):
        if not sb().table("items").select("id").is_("embedding", "null").in_("source_id", _source_ids()).limit(1).execute().data:
            break
        hits += score()
    print(f"scored → {hits} new hits")
    print(f"reported {report()}")
    if translate_pass(titles_only=True) == 0:    # titles first; see ingest_pass()
        translate_pass()
    # After English, because a Norwegian headline is only wanted for items whose language
    # the English pass has already detected -- translate_nb_pass filters on lang not null.
    translate_nb_pass()
    site = archive_site.build()          # refresh the browsable index over the archive
    if site:
        print(f"archive index → {site}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--seed", action="store_true"); ap.add_argument("--loop", action="store_true")
    ap.add_argument("--backfill", action="store_true", help="enrich thin bodies, then re-embed and re-score")
    ap.add_argument("--ingest", action="store_true", help="fetch + score every newsroom; no drafting, no delivery")
    ap.add_argument("--run", metavar="PRODUCT_ID",
                    help="draft one product now, as the worker's /run/<product-id> does")
    ap.add_argument("--newsroom", help="disambiguate a product id that both desks define")
    ap.add_argument("--oslo-hour", type=int, metavar="H",
                    help="with --run: do nothing unless it is currently hour H in Europe/Oslo")
    ap.add_argument("--offline", action="store_true",
                    help="build a copy on the shared drive that opens with no server and no login")
    ap.add_argument("--publish", action="store_true",
                    help="upload the archive index to Supabase Storage and print a signed link")
    ap.add_argument("--translate-cited", action="store_true",
                    help="translate the titles every already-drafted report cites, newest first")
    ap.add_argument("--public", action="store_true",
                    help="build the hostable site: the digests only, no archive pages")
    ap.add_argument("--deploy", action="store_true",
                    help="build the hostable site and push it to Cloudflare Pages")
    ap.add_argument("--serve", action="store_true",
                    help="serve a built site on 127.0.0.1 so it can be read with no host, no login")
    ap.add_argument("--port", type=int, default=8787, help="with --serve (default 8787)")
    ap.add_argument("--translate", action="store_true",
                    help="fill in English twins for every untranslated item, rewrite the archive, stop")
    a = ap.parse_args()
    if a.seed:
        seed()
    if a.backfill:
        backfill(); raise SystemExit(0)
    if a.run:
        # Before the while loop, like --ingest: falling through into one_pass() would draft a
        # SECOND time via report() and deliver both.
        if a.oslo_hour is not None:
            # NOT an equality test any more. It was, until 2026-10-04, and that is how a whole
            # day's brief went missing: the machine was asleep at the scheduled time, Windows ran
            # the task on wake (StartWhenAvailable), and the guard saw Oslo hour 11 instead of 6
            # and exited 0. A catch-up run that deliberately does nothing is worse than no
            # catch-up at all, because the exit code says success and nothing says there is no
            # brief today.
            #
            # So: do not draft BEFORE the intended hour, and draft at most once per Oslo day. The
            # DST double-registration the equality test existed to handle is now handled by the
            # once-a-day check instead -- the second trigger finds today's brief and skips -- and
            # a late run still produces the brief, late, which is the outcome we actually want.
            h = oslo_hour()
            if h < a.oslo_hour:
                print(f"skip: Oslo hour is {h:02d}, waiting for {a.oslo_hour:02d}")
                raise SystemExit(0)
            if drafted_today(a.run, a.newsroom):
                print(f"skip: {a.run} already has a report for today (Oslo)")
                raise SystemExit(0)
            if h > a.oslo_hour:
                print(f"catching up: Oslo hour is {h:02d}, scheduled for {a.oslo_hour:02d}, "
                      f"no report yet today -- drafting now")
        run_product(a.run, a.newsroom); raise SystemExit(0)
    if a.translate_cited:
        # Newest first: the front page shows the latest brief, so that one's English column is the
        # one worth fixing first if the run is cut short by an API outage.
        ids = [r["id"] for r in sb().table("reports").select("id")
               .order("created_at", desc=True).execute().data]
        total = sum(translate_cited(i) for i in ids)
        print(f"translated {total} cited titles across {len(ids)} reports")
        raise SystemExit(0)
    if a.serve:
        # Before --public and --offline so `--serve --public` reads an existing build rather than
        # rebuilding first: serving is for looking at what is already there.
        publish_mod.serve(a.port, public_site=a.public); raise SystemExit(0)
    if a.offline:
        publish_mod.offline(); raise SystemExit(0)
    if a.deploy:
        # Before --public, so `--deploy` alone does the build too rather than deploying a stale one.
        publish_mod.deploy(sb()); raise SystemExit(0)
    if a.public:
        publish_mod.public(sb()); raise SystemExit(0)
    if a.publish:
        publish_mod.publish(sb()); raise SystemExit(0)
    if a.translate:
        # Before --ingest and before the while loop, for the same reason --ingest is: falling
        # through into one_pass() would draft and deliver. Drains rather than running one batch,
        # because the first run has the whole archive to catch up on; it stops as soon as a pass
        # translates nothing, so items that fail permanently cannot spin it.
        while translate_pass(shortest_first=True, titles_only=True):
            pass                         # every title first -- ~58 requests for the whole archive
        while translate_pass(shortest_first=True):
            pass                         # then bodies, for as long as the quota lasts
        sync_archive()                  # rewrite every archive file, now with its English twin
        raise SystemExit(0)
    if a.ingest:
        # Before the while loop on purpose: --ingest must never fall through into one_pass(), which
        # drafts and delivers. --seed does fall through, which is how a rikspolitikk seed once ran
        # Nord-Norge's regional-monitor and died looking for a product that does not exist there.
        ingest_pass(); raise SystemExit(0)
    while True:
        one_pass()
        if not a.loop:
            break
        time.sleep(int(os.environ.get("INTERVAL_SECONDS", "3600")))
