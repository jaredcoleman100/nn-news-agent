"""HTTP entrypoints. Each maps a trigger to a Job and runs the pipeline. Nothing here knows about genres or regions."""
from __future__ import annotations
import base64, hmac, io, json, os, shutil, tarfile, tempfile, time
from pathlib import Path
from typing import Any
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from core import pipeline, registry
from core.products import (load_product, list_products, list_newsrooms, resolve_product,
                           products_with_trigger)
from core.schema import Report

app = FastAPI()
SECRET = os.environ.get("WEBHOOK_SECRET", "")
# Fallback only. Every route now resolves the newsroom from the work itself — the product id for
# a scheduled run, the hit row for a webhook — because this process serves more than one newsroom
# and a module-level constant cannot. Kept for /hit's product default and for single-newsroom setups.
NEWSROOM = os.environ.get("NEWSROOM_ID", "nord-norge")


def _auth(secret: str) -> None:
    if SECRET and secret != SECRET:
        raise HTTPException(401)


ARCHIVE_USER = os.environ.get("ARCHIVE_USER", "")
ARCHIVE_PASSWORD = os.environ.get("ARCHIVE_PASSWORD", "")
ARCHIVE_BUCKET = os.environ.get("ARCHIVE_BUCKET", "archive")
ARCHIVE_OBJECT = os.environ.get("ARCHIVE_OBJECT", "site.tar.gz")
# How long to trust the extracted copy before asking Storage whether it changed. One HEAD-ish call
# per minute, not per request.
ARCHIVE_TTL = int(os.environ.get("ARCHIVE_TTL", "60"))

_site: dict[str, Any] = {"dir": None, "version": None, "checked": 0.0}

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".json": "application/json",
    ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".webp": "image/webp", ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8", ".xml": "application/xml",
}


def _basic_auth(authorization: str) -> None:
    """Browser-native auth for the archive.

    Basic rather than a `?key=` query parameter on purpose: a secret in a URL lands in browser
    history, in referrer headers, in proxy logs, and in whatever chat message the link is pasted
    into. A header does not, and the browser prompts for it, so the URL stays shareable. Safe only
    because fly.toml sets force_https.

    Constant-time compare so the password cannot be recovered a character at a time from response
    timings.
    """
    if not (ARCHIVE_USER and ARCHIVE_PASSWORD):
        raise HTTPException(503, "archive access is not configured")
    expected = "Basic " + base64.b64encode(f"{ARCHIVE_USER}:{ARCHIVE_PASSWORD}".encode()).decode()
    if not hmac.compare_digest(authorization, expected):
        raise HTTPException(401, headers={"WWW-Authenticate": 'Basic realm="nn-news-agent archive"'})


def _ensure_site() -> Path:
    """Return a directory holding the extracted site, refreshing it when Storage has a newer copy.

    The site is ~2500 files. Uploading and fetching them individually would be thousands of API
    calls per publish, so it travels as ONE tar.gz and is unpacked here. That also makes a publish
    atomic: a half-uploaded tree can never be served, because the object swaps in one operation.
    """
    from plugins.loaders.db import sb

    now = time.time()
    if _site["dir"] and now - _site["checked"] < ARCHIVE_TTL:
        return Path(_site["dir"])

    store = sb().storage.from_(ARCHIVE_BUCKET)
    try:
        info = store.info(ARCHIVE_OBJECT)
        version = str(info.get("version") or info.get("etag") or info.get("last_modified") or "")
    except Exception as ex:  # noqa: BLE001
        if _site["dir"]:
            _site["checked"] = now          # keep serving the copy we have rather than 500ing
            return Path(_site["dir"])
        raise HTTPException(404, f"no archive published yet ({ex}); run: python run.py --publish")

    _site["checked"] = now
    if _site["dir"] and version == _site["version"]:
        return Path(_site["dir"])

    blob = store.download(ARCHIVE_OBJECT)
    target = Path(tempfile.mkdtemp(prefix="nn-archive-"))
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        # filter="data" refuses absolute paths, "..", symlinks and device files -- a tarball is
        # attacker-shaped input in general, and this one is unpacked with the worker's privileges.
        tar.extractall(target, filter="data")

    old = _site["dir"]
    _site["dir"], _site["version"] = str(target), version
    if old:
        shutil.rmtree(old, ignore_errors=True)
    return target


def _serve(rel: str, authorization: str) -> Response:
    _basic_auth(authorization)
    root = _ensure_site()

    candidate = (root / rel.lstrip("/")).resolve() if rel.strip("/") else (root / "index.html")
    if candidate.is_dir():
        candidate = candidate / "index.html"
    # Path traversal guard: resolve first, then require the result to be inside the extracted tree.
    # Checking the raw string for ".." is not enough once encodings and symlinks are in play.
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        raise HTTPException(404, "not found")
    if not candidate.is_file():
        raise HTTPException(404, "not found")

    media = CONTENT_TYPES.get(candidate.suffix.lower(), "application/octet-stream")
    return Response(content=candidate.read_bytes(), media_type=media,
                    # noindex belt-and-braces: the site is behind a password, but it carries other
                    # outlets' article text and must never reach a search index.
                    headers={"Cache-Control": "private, max-age=60",
                             "X-Robots-Tag": "noindex, nofollow"})


@app.get("/archive")
def archive_root() -> Response:
    """Redirect to the trailing slash, which the relative links depend on.

    Every internal link in the site is relative, so one build works both here and opened off the
    shared drive as a file:// URL. Relative resolution needs the trailing slash: from `/archive` a
    browser treats "archive" as a filename and resolves `item/x/` against its parent, landing on
    `/item/x/`. From `/archive/` it resolves correctly.

    Deliberately before the auth check -- a redirect reveals nothing, and challenging here would
    make the browser prompt twice, once per URL.
    """
    return RedirectResponse("/archive/", status_code=308)


@app.get("/archive/{path:path}")
def archive_path(path: str, authorization: str = Header(default="")) -> Response:
    """Serve the Eleventy-built archive.

    Exists because a Supabase signed URL cannot render HTML: Storage returns signed objects as
    text/plain with X-Content-Type-Options: nosniff whatever their stored type, since the token's
    scope is `download`. The only rendering route is /object/public/, which needs a public bucket
    -- and this archive holds near-complete article text from other newsrooms plus translations of
    it, so public is the wrong answer. Reading it here with the service-role key keeps the bucket
    private and puts real auth in front.
    """
    return _serve(path, authorization)


def _guard() -> None:
    from plugins.loaders.db import sb
    if sb().table("config").select("value").eq("key", "paused").single().execute().data["value"]:
        raise HTTPException(503, "paused")


def _store(r: Report) -> Report:
    from plugins.loaders.db import sb
    job = sb().table("jobs").insert({"product_id": r.job.product_id, "newsroom_id": r.job.newsroom_id,
                                     "trigger": r.job.trigger, "payload": r.job.payload}).execute().data[0]
    r.job.id = job["id"]
    row = sb().table("reports").insert(r.to_row()).execute().data[0]
    r.id = row["id"]
    sb().table("runs").insert({"job_id": job["id"], "report_id": r.id, "status": "ok", "steps": r.log,
                               "input_tokens": r.usage["input"], "output_tokens": r.usage["output"]}).execute()
    if r.job.trigger == "hit":
        sb().table("hits").update({"status": "reported"}).eq("id", r.job.payload["hit_id"]).execute()
    return r


def _route_hit(hit_id: int) -> tuple[str, str | None]:
    """(newsroom, product_id or None) for a hit. Mirrors run.py report(): the hit's own
    newsroom_id, then the source's `config.product` override, then that newsroom's default hit
    product. Both paths must agree, or a story drafts differently depending on whether the webhook
    or the poller reached it first.

    Returns None for the product when the newsroom has no per-hit desk at all, which is the
    rikspolitikk case — its only product is a scheduled digest. Returning a name that does not
    exist there would raise FileNotFoundError inside a webhook and look like an outage.
    """
    from plugins.loaders.db import sb
    hit = sb().table("hits").select("item_id,newsroom_id").eq("id", hit_id).single().execute().data
    newsroom = hit.get("newsroom_id") or NEWSROOM
    candidates = products_with_trigger(newsroom, "hit")

    item = sb().table("items").select("source_id").eq("id", hit["item_id"]).single().execute().data
    if item.get("source_id"):
        src = sb().table("sources").select("config").eq("id", item["source_id"]).single().execute().data
        override = (src.get("config") or {}).get("product")
        if override:                       # a per-source route is an explicit editorial decision
            return newsroom, override
    env = (os.environ.get(f"HIT_PRODUCT_{newsroom.replace('-', '_').upper()}")
           or os.environ.get("HIT_PRODUCT"))
    if env and env in candidates:
        return newsroom, env
    if len(candidates) == 1:
        return newsroom, candidates[0]
    # Several hit desks and no env preference: keep the historical default if this newsroom has it.
    return newsroom, "regional-monitor" if "regional-monitor" in candidates else None


@app.post("/hit")
def on_hit(payload: dict, x_webhook_secret: str = Header(default="")) -> dict[str, Any]:
    _auth(x_webhook_secret); _guard()
    rec = payload.get("record") or payload
    newsroom, product_id = _route_hit(rec["id"])
    if product_id is None:
        return {"skipped": f"{newsroom} has no per-hit product"}
    product = load_product(newsroom, product_id)
    # A newsroom whose desk is a scheduled digest (the satire desk) has no per-hit product. Before
    # this check, every rikspolitikk hit INSERT fired this webhook and was drafted with Nord-Norge's
    # regional-monitor template: a wrong genre, under the wrong newsroom, delivered to the wrong editor.
    if product["trigger"] != "hit":
        return {"skipped": f"{newsroom}/{product_id} is trigger={product['trigger']}, not per-hit"}
    job = registry.get("trigger", "hit").to_job(product, {"hit_id": rec["id"]})
    r = pipeline.run(job, product, store=_store)
    return {"report_id": r.id, "gate": r.gate}


@app.post("/run/{product_id}")
def on_schedule(product_id: str, payload: dict | None = None, x_webhook_secret: str = Header(default="")) -> dict[str, Any]:
    """Scheduled or ad-hoc run of any product, in any newsroom (cron → POST /run/satire-desk).
    The newsroom comes from the product id; `payload.newsroom_id` disambiguates a shared id."""
    _auth(x_webhook_secret); _guard()
    product = resolve_product(product_id, (payload or {}).get("newsroom_id"))
    job = registry.get("trigger", product["trigger"]).to_job(product, payload or {})
    r = pipeline.run(job, product, store=_store)
    return {"report_id": r.id, "gate": r.gate, "newsroom": product["newsroom_id"]}


def _ingest_pass(newsrooms: list[str]) -> None:
    """One fetch + drain-the-scoring-backlog pass. Runs in a background task, never in the request.

    `run` is imported here rather than at module scope on purpose. Importing it pulls in
    core.embeddings, which reads EMBEDDER at import time and would make the whole worker — drafting
    included — fail to start on an embedder misconfiguration. Drafting does not embed, and should
    not be able to break because ingest is broken.
    """
    import run                                     # noqa: PLC0415 - deliberate, see above
    try:
        n = run.fetch()                            # sources are global; one pass serves everyone
        print(f"ingest: fetched {n} new items", flush=True)
    except Exception as ex:                        # noqa: BLE001
        print(f"ingest: fetch failed: {ex}", flush=True)
        return
    from plugins.loaders.db import sb
    for nr in newsrooms:
        run.NEWSROOM = nr                          # module global, read by _source_ids()/score()
        ids = run._source_ids()
        scored = 0
        for _ in range(int(os.environ.get("SCORE_BATCHES", "12"))):
            if not sb().table("items").select("id").is_("embedding", "null") \
                     .in_("source_id", ids).limit(1).execute().data:
                break
            try:
                scored += run.score()
            except Exception as ex:                # noqa: BLE001
                print(f"ingest[{nr}]: score failed: {ex}", flush=True)
                break
        print(f"ingest[{nr}]: {scored} hits", flush=True)


@app.post("/ingest")
def on_ingest(background: BackgroundTasks, payload: dict | None = None,
              x_webhook_secret: str = Header(default="")) -> dict[str, Any]:
    """Kick a fetch+score pass and return immediately.

    Deliberately 202-and-background: a full pass fetches ~27 sources, enriches article pages and
    embeds the backlog in batches of 64, which runs for minutes. pg_net gives up at its
    timeout_milliseconds and Fly would hold a request open the whole time, so the cron would record
    a failure for work that actually succeeded.
    """
    _auth(x_webhook_secret); _guard()
    newsrooms = (payload or {}).get("newsrooms") or list_newsrooms()
    background.add_task(_ingest_pass, newsrooms)
    return {"accepted": newsrooms, "status": "running in background"}


@app.get("/products")
def products() -> dict[str, Any]:
    return {"newsrooms": {n: list_products(n) for n in list_newsrooms()}, "default_newsroom": NEWSROOM}


@app.post("/slack/reaction")
async def on_reaction(request: Request) -> dict:
    """Slack Events API: reactions → editor_decision + precedent; threaded replies → editor_reason."""
    from plugins.deliverers import slack_events
    body = await request.body()
    if not slack_events.verify(body, request.headers.get("x-slack-request-timestamp", ""), request.headers.get("x-slack-signature", "")):
        raise HTTPException(401)
    payload = json.loads(body)
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}
    return slack_events.handle(payload.get("event", {}))


@app.post("/document")
def on_document(payload: dict, x_webhook_secret: str = Header(default="")) -> dict[str, Any]:
    """Document drop: {"product_id": "document-story", "path"|"url": ..., "title"?: ..., "sender"?: ...}"""
    _auth(x_webhook_secret); _guard()
    product = load_product(NEWSROOM, payload.get("product_id", "document-story"))
    job = registry.get("trigger", "document").to_job(product, payload)
    r = pipeline.run(job, product, store=_store)
    return {"report_id": r.id, "gate": r.gate}


@app.get("/health")
def health() -> dict:
    import sys; sys.path.insert(0, "ethics"); import server
    return {"ok": True, "corpus": server.corpus_status()}
