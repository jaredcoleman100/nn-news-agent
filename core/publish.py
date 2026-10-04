"""Build the Eleventy archive site and upload it for the worker's /archive route to serve.

    PYTHONPATH=. python run.py --publish

The site source (config, templates, data layer) lives in the repo at `site/`. The **toolchain**
does not: `node_modules` is ~130 packages of thousands of files, and the repo sits on a shared
Google Drive where that would sync to everyone on it -- the same reason the venv and .env live
under ~/.config and ~/.venvs rather than in the repo. It is installed once with:

    npm install --prefix ~/.nn-news-site

The whole site travels as ONE tar.gz. It is ~2500 files; uploading and fetching them individually
would be thousands of Storage calls per publish. A single object also makes a publish atomic --
a half-uploaded tree can never be served, because the object swaps in one operation.

The bucket stays **private**. The archive carries near-complete article text from other newsrooms
plus English translations of it, which are derivative works: internally an ordinary research
archive, on a public URL an unlicensed mirror. A Supabase signed URL is not an option either --
Storage serves signed objects as text/plain with nosniff whatever their stored type, because the
token's scope is `download`. So the worker reads the object with the service-role key and serves
it behind HTTP Basic.

    SITE_TOOLCHAIN=~/.nn-news-site   where node_modules and the build output live
    ARCHIVE_BUCKET=archive           bucket name
    ARCHIVE_PUBLISH=1                also publish from the hourly sync_archive()
    ARCHIVE_URL=https://...          where to tell the operator the site is served
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

from core import hits_export, reports_export
from core.archive import ARCHIVE_DIR

ROOT = Path(__file__).resolve().parents[1]
BUCKET = os.environ.get("ARCHIVE_BUCKET", "archive")
OBJECT = os.environ.get("ARCHIVE_OBJECT", "site.tar.gz")
TOOLCHAIN = Path(os.environ.get("SITE_TOOLCHAIN", str(Path.home() / ".nn-news-site")))
SERVED_AT = os.environ.get("ARCHIVE_URL", "https://nn-news-agent.fly.dev/archive")
SITE_SRC = ROOT / "site"


def _eleventy() -> Path:
    """The Eleventy binary in the off-drive toolchain. npm writes a .cmd shim on Windows."""
    binroot = TOOLCHAIN / "node_modules" / ".bin"
    for name in ("eleventy.cmd", "eleventy"):
        candidate = binroot / name
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"Eleventy is not installed in {TOOLCHAIN}. Install the toolchain once with:\n"
        f"    npm install --prefix {TOOLCHAIN}\n"
        f"(deliberately outside the repo: node_modules must not sync to the shared drive)")


# Output dirs this process already holds the lock on. offline()/public()/publish() take it for the
# whole build-then-copy, and the build() inside them must not deadlock on it.
_HELD: set[Path] = set()


@contextlib.contextmanager
def _build_lock(out: Path):
    """Serialise builds that share an output directory.

    `build()` starts by deleting the output tree, so two builds at once destroy each other: a
    second one wiping `_site` while the first is partway through copying it to the drive leaves a
    half-copied archive site and a wall of WinError 3. Observed, not hypothetical.

    An exclusive-create lock file rather than a mutex, because the racing processes are separate
    Python runs -- a scheduled task and a command typed by hand. A stale lock from a killed build
    is cleared by deleting the file the error names.
    """
    if out in _HELD:
        yield
        return
    lock = out.with_suffix(".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError(
            f"another build is already writing {out.name}. If nothing is running, delete {lock}"
        ) from None
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        _HELD.add(out)
        yield
    finally:
        _HELD.discard(out)
        lock.unlink(missing_ok=True)


def build(sb=None, public: bool = False) -> Path:
    """Run Eleventy. Returns the output directory.

    `sb` refreshes archive/hits.json and archive/reports.json first, so the front page shows the
    digest that was actually drafted and the category pages reflect the current hits, rather than
    whatever the last export left behind. Omitted for an offline rebuild that only wants what is
    already on disk re-rendered.

    `public=True` builds the hostable subset: the digests, with no archive pages at all. The two
    builds go to different output directories so one can never be uploaded in place of the other --
    the whole difference between them is whether the tree contains other newsrooms' article text.
    """
    if sb is not None:
        hits_export.export(sb)
        reports_export.export(sb)
        reports_export.export_pipeline(sb)
        # Pictures for the entities the briefs actually named. Cached, so a build only reaches
        # Commons for an entity it has not seen before.
        try:
            from core import images
            import json as _json
            _r = _json.loads(reports_export.REPORTS_FILE.read_text(encoding="utf-8"))
            _ents = sorted({st.get("entity") for rep in _r for st in rep.get("stories", [])
                            if st.get("entity")})
            images.export(_ents)
        except Exception as _ex:  # noqa: BLE001 - a picture is never worth failing a build over
            print(f"  images: skipped ({type(_ex).__name__}: {str(_ex)[:60]})")
    out = TOOLCHAIN / ("_public" if public else "_site")
    with _build_lock(out):
        # Eleventy does not remove files it no longer generates, so a page that stops existing -- a
        # renamed slug, a deduped duplicate, a category that lost its last hit -- would otherwise
        # stay in the output forever and ship in every tarball. Start from empty.
        if out.exists():
            shutil.rmtree(out, ignore_errors=True)
        env = {**os.environ,
               "ARCHIVE_ITEMS": str(ARCHIVE_DIR),
               "ELEVENTY_OUT": str(out),
               "SITE_PUBLIC": "1" if public else "0"}
        # cwd is the repo's site/ so Eleventy's input, _includes and _data resolve there; the
        # binary and the output live in the toolchain.
        proc = subprocess.run([str(_eleventy()), "--config=eleventy.config.js"],
                              cwd=str(SITE_SRC), env=env, capture_output=True, text=True,
                                                    encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-15:]
            raise RuntimeError("eleventy build failed:\n  " + "\n  ".join(tail))
        written = [ln for ln in (proc.stdout or "").splitlines() if "Wrote" in ln]
        print(f"  eleventy{' (public)' if public else ''}: "
              f"{written[-1].strip() if written else 'built'}")
        if public:
            _assert_no_archive(out)
    return out


def _write_sitemap(out: Path) -> int:
    """Write sitemap.xml by walking the BUILT directory, not Eleventy's collections.

    WHY NOT A TEMPLATE
    The obvious version is a Nunjucks template over `collections.all`, and it is quietly wrong: a
    paginated template appears in that collection ONCE, at its first page's URL. The first attempt
    listed 12 URLs for a 71-page site -- one digest of twenty-five, one Norlit piece of seventeen,
    one region of nine -- and nothing about the output said so. Walking the output directory cannot
    drift from what is actually deployed, which is the only thing a sitemap should describe.

    Skips 404.html (a crawl error by design) and anything under a path the public build should not
    have; _assert_no_archive has already run, so that second case is belt and braces.
    """
    origin = os.environ.get("SITE_ORIGIN", "https://norway-royal-news.pages.dev").rstrip("/")
    urls = []
    for f in sorted(out.rglob("*.html")):
        rel = f.relative_to(out).as_posix()
        if rel == "404.html":
            continue
        urls.append("/" if rel == "index.html" else
                    "/" + (rel[:-len("index.html")] if rel.endswith("/index.html") else rel))
    nl = chr(10)
    body = nl.join(f"  <url><loc>{origin}{u}</loc></url>" for u in urls)
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>' + nl
        + '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + nl
        + body + nl + "</urlset>" + nl, encoding="utf-8")
    return len(urls)


def _assert_no_archive(out: Path) -> None:
    """Refuse to hand back a public build that contains an archive page.

    This is the one invariant worth a hard check rather than a comment. The exclusion lives in
    eleventy.config.js, one env var away from being wrong, and the failure mode is not a broken
    page -- it is 1,900 articles of other newsrooms' text on an open URL, which is the kind of
    mistake you find out about from someone else.
    """
    leaked = sorted(d.name for d in out.iterdir()
                    if d.is_dir() and d.name in
                    {"item", "everything", "browse", "day", "source", "category",
                     "categories", "outlet"})
    if leaked:
        raise RuntimeError(
            "public build contains archive pages: " + ", ".join(leaked) +
            "\nSITE_PUBLIC did not reach Eleventy. Nothing was uploaded.")


# Where the offline copy lands on the shared drive. Beside the item tree, not inside it:
# archive.ARCHIVE_DIR is archive/items and is globbed for *.md, so HTML here cannot collide.
OFFLINE_DIR = Path(os.environ.get("ARCHIVE_OFFLINE_DIR", str(ARCHIVE_DIR.parent / "site")))


def offline() -> Path:
    """Build a copy on the shared drive that opens with no server and no login.

    Same build as the hosted site -- every internal link is relative, so the identical output works
    served under /archive/ and opened as a file:// URL. Open `archive/site/index.html` from the
    drive and it just works, including when the Fly machine is asleep.

    The cost is Drive sync: ~2500 files land on a shared drive and replicate to everyone on it.
    That is the point of an offline copy, but it is why this is a separate command rather than
    something the hourly pass does.
    """
    # no sb: reuse the last hits.json rather than requiring the network. The lock spans the copy
    # as well as the build, because copytree reads the tree a second build would delete.
    with _build_lock(TOOLCHAIN / "_site"):
        built = build()
        if OFFLINE_DIR.exists():
            shutil.rmtree(OFFLINE_DIR, ignore_errors=True)
        shutil.copytree(built, OFFLINE_DIR)
    pages = sum(1 for p in OFFLINE_DIR.rglob("*.html"))
    print(f"offline copy: {pages:,} pages -> {OFFLINE_DIR}")
    print(f"  open {OFFLINE_DIR / 'index.html'}")
    return OFFLINE_DIR


def _tarball(site: Path) -> bytes:
    buf = io.BytesIO()
    # Deterministic-ish: sorted walk, so an unchanged site produces a byte-identical archive and
    # the object's version only moves when the content actually did.
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in sorted(site.rglob("*")):
            if path.is_file():
                info = tar.gettarinfo(str(path), arcname=str(path.relative_to(site)).replace("\\", "/"))
                info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "", ""
                with open(path, "rb") as fh:
                    tar.addfile(info, fh)
    return buf.getvalue()


def publish(sb) -> str | None:
    """Build the site, upload it as one object, and return the URL it is served at."""
    with _build_lock(TOOLCHAIN / "_site"):
        site = build(sb)
        if not (site / "index.html").exists():
            print("publish: build produced no index.html")
            return None
        # Inside the lock: _tarball walks the tree, same hazard as offline()'s copytree.
        data = _tarball(site)
        pages = sum(1 for p in site.rglob("*.html"))

    store = sb.storage.from_(BUCKET)
    # Delete before uploading rather than upserting: an upsert replaces the bytes but keeps the
    # existing object's stored content-type, so one bad first upload pins it permanently.
    try:
        store.remove([OBJECT])
    except Exception:  # noqa: BLE001
        pass
    # cache-control must be a NUMBER of seconds: storage3 formats it as `max-age={value}`, so
    # "no-cache" yields the malformed `max-age=no-cache`.
    store.upload(OBJECT, data, {"content-type": "application/gzip", "upsert": "true",
                                "cache-control": "60"})
    print(f"published {pages:,} pages ({len(data):,} bytes gzipped) to {BUCKET}/{OBJECT}")
    print(f"  served at {SERVED_AT}")
    return SERVED_AT


# Where the hostable build lands. Off the drive by default, next to the toolchain: it is a build
# artefact, and 30-odd files of it syncing to everyone on the shared drive serves nobody.
PUBLIC_DIR = Path(os.environ.get("SITE_PUBLIC_DIR", str(TOOLCHAIN / "public")))


def public(sb=None) -> Path:
    """Build the hostable site -- digests only -- and leave it on disk for a deploy step.

        PYTHONPATH=. python run.py --public

    Deliberately does NOT upload anywhere. Choosing where this goes is an editorial decision about
    publishing NRK-branded summaries under someone's name, not a build step, and the host has to be
    named once by a person before a command does it on a timer.
    """
    with _build_lock(TOOLCHAIN / "_public"):
        built = build(sb, public=True)
        if PUBLIC_DIR.exists():
            shutil.rmtree(PUBLIC_DIR, ignore_errors=True)
        shutil.copytree(built, PUBLIC_DIR)

        # The access gate, OFF by default since 2026-10-02 on the editor's instruction ("take off
        # the gate, make it all public"). It is a switch rather than a deletion because the worker
        # itself is still correct and re-gating should not need a code change:
        #
        #     SITE_GATE=1 python run.py --deploy    # back behind the key
        #
        # Pages runs `_worker.js` at the root of the uploaded directory instead of serving files
        # directly, so every request goes through it and the static assets come back via
        # env.ASSETS. A deploy WITHOUT the file replaces the whole deployment, so simply not
        # copying it is enough to remove a gate that is already live -- there is no separate
        # teardown step. SITE_KEY stays set in the Pages project; with no worker reading it, it is
        # inert, and leaving it means re-gating is one env var and not a secret to re-mint.
        # The sitemap, after the build so it describes the real output. Only for the public
        # build: there is no internal sitemap, because robots.txt disallows that build entirely.
        n = _write_sitemap(PUBLIC_DIR)
        print(f"  sitemap: {n} urls -> sitemap.xml")

        gate = SITE_SRC / "public-worker.js"
        if os.environ.get("SITE_GATE") == "1":
            if not gate.exists():
                raise SystemExit("SITE_GATE=1 but site/public-worker.js is missing")
            shutil.copy2(gate, PUBLIC_DIR / "_worker.js")
            print("  gate: _worker.js in place (site is behind the key)")
        else:
            print("  gate: OFF -- this build is public to anyone with the URL")
    pages = sorted(p.relative_to(PUBLIC_DIR).as_posix() for p in PUBLIC_DIR.rglob("*.html"))
    print(f"public build: {len(pages)} pages -> {PUBLIC_DIR}")
    for page in pages[:8]:
        print(f"    {page}")
    if len(pages) > 8:
        print(f"    ... and {len(pages) - 8} more")
    print(f"  preview it with:  python run.py --serve --public")
    return PUBLIC_DIR


def serve(port: int = 8787, public_site: bool = False) -> None:
    """Serve a built site on localhost, so it can be read without a host and without a login.

        PYTHONPATH=. python run.py --serve            the internal archive
        PYTHONPATH=. python run.py --serve --public   the hostable subset

    Bound to 127.0.0.1, not 0.0.0.0. The internal build carries other newsrooms' article text, and
    a server on the LAN is a server on whatever network this laptop joins next.
    """
    import functools
    import http.server
    import socketserver

    root = PUBLIC_DIR if public_site else (TOOLCHAIN / "_site")
    if not (root / "index.html").exists():
        which = "--public" if public_site else "--offline"
        raise FileNotFoundError(f"nothing built at {root}. Run `python run.py {which}` first.")

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
        print(f"serving {root}")
        print(f"  http://127.0.0.1:{port}/    (ctrl-c to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")


# ---------------------------------------------------------------- deploying the public site

# Cloudflare Pages, chosen 2026-09-27. It deploys a directory straight from this machine with no
# git remote, which matters because the repo lives on a shared Google Drive and is not a git
# checkout. Free, and the whole site is 15 pages.
CF_PROJECT = os.environ.get("CF_PAGES_PROJECT", "norway-royal-news")


def _wrangler() -> Path:
    binroot = TOOLCHAIN / "node_modules" / ".bin"
    for name in ("wrangler.cmd", "wrangler"):
        candidate = binroot / name
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"wrangler is not installed in {TOOLCHAIN}. Install it once with:\n"
        f"    npm install --prefix {TOOLCHAIN} wrangler")


# Every place wrangler might drop a generated config. Checked before and after a deploy.
_CONFIG_DIRS = (ROOT, TOOLCHAIN, PUBLIC_DIR)
_CONFIG_NAMES = ("wrangler.json", "wrangler.jsonc", "wrangler.toml")


def _wrangler_configs() -> set[Path]:
    return {d / n for d in _CONFIG_DIRS for n in _CONFIG_NAMES if (d / n).exists()}


def _no_stray_config(before: set[Path]) -> None:
    """Delete, and complain about, any config wrangler generated during a deploy.

    Left in place these are live: the next bare `wrangler` run in that directory reads the guessed
    `assets.directory` and republishes whatever it names. The one written on 2026-09-27 pointed at
    the internal archive.
    """
    stray = _wrangler_configs() - before
    for path in sorted(stray):
        path.unlink(missing_ok=True)
    if stray:
        raise RuntimeError(
            "wrangler generated config during the deploy and it has been removed: "
            + ", ".join(str(p) for p in sorted(stray))
            + ". Re-run the deploy and check what it published.")


def deploy(sb=None, build_first: bool = True) -> str | None:
    """Build the public site and push it to Cloudflare Pages.

        PYTHONPATH=. python run.py --deploy

    Requires `wrangler login` once, interactively, in a browser -- that is the account owner's
    step and cannot be done from here. After that this is non-interactive and safe on a timer.

    Only ever deploys PUBLIC_DIR, which `build(public=True)` has already run _assert_no_archive()
    over. There is deliberately no flag to deploy the internal build: the thing that must never
    happen is one command away otherwise.
    """
    # Checked BEFORE the build, because the build is the slow part and this failure is certain.
    #
    # `wrangler login` stores an OAuth token that works when a person is at the keyboard and is
    # refused outright in a non-interactive session -- which is exactly what Task Scheduler gives
    # you. So a deploy that works by hand fails every night with a message about API tokens, in a
    # log file nobody opens. Found by running the scheduled task rather than trusting it.
    #
    # The fix is a scoped API token in ~/.config/nn-news-agent/.env, which run.py loads into the
    # environment before wrangler inherits it:
    #     CLOUDFLARE_API_TOKEN=...      Account > Cloudflare Pages > Edit
    # No interactivity check here: `sys.stdin.isatty()` is True under Task Scheduler with output
    # redirected, so guessing gets it wrong in exactly the case that matters. The condition is
    # detected from wrangler's own output instead, below.
    site = public(sb) if build_first else PUBLIC_DIR
    if not (site / "index.html").exists():
        print(f"deploy: nothing built at {site}")
        return None
    _assert_no_archive(site)        # again, on the exact bytes about to be uploaded

    # cwd is PUBLIC_DIR, and that is not cosmetic.
    #
    # wrangler 4.142 "autoconfig" silently rewrites `pages project create` into `wrangler deploy`,
    # and to do that it WRITES a wrangler.jsonc into the current directory, guessing the asset
    # directory from what it finds there. Run from the toolchain it guessed `_site` -- the internal
    # archive -- and published 7,718 pages of other newsrooms' article text as a Worker before
    # anyone asked it to. That happened here on 2026-09-27; the Worker was deleted minutes later.
    #
    # Running from PUBLIC_DIR means the only directory it can possibly guess is the one that has
    # already passed _assert_no_archive(). _no_stray_config() below then fails the deploy if a
    # config file appeared anyway, rather than letting it sit there arming the next run.
    before = _wrangler_configs()
    proc = subprocess.run(
        [str(_wrangler()), "pages", "deploy", ".",
         "--project-name", CF_PROJECT, "--commit-dirty=true"],
        cwd=str(site), capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    _no_stray_config(before)
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        # The one failure worth naming, because it only happens on the scheduled run and the real
        # message is buried in wrangler's output: `wrangler login` stores an OAuth token that is
        # refused in a non-interactive session, so a deploy that works by hand fails every night.
        if "CLOUDFLARE_API_TOKEN" in out:
            raise RuntimeError(
                "wrangler will not use its stored OAuth login in a non-interactive session "
                "(Task Scheduler), so the scheduled deploy cannot authenticate.\n"
                "  Fix once: create a token with the 'Cloudflare Pages: Edit' permission at\n"
                "  https://dash.cloudflare.com/profile/api-tokens and add it to\n"
                "  ~/.config/nn-news-agent/.env as  CLOUDFLARE_API_TOKEN=...\n"
                "  run.py loads that file, and wrangler inherits the environment from it.")
        tail = out.strip().splitlines()[-12:]
        raise RuntimeError("wrangler deploy failed:\n  " + "\n  ".join(tail))
    urls = [w.strip() for ln in out.splitlines() for w in ln.split()
            if w.startswith("https://") and "pages.dev" in w]
    pages = sum(1 for p in site.rglob("*.html"))
    url = urls[-1] if urls else None
    print(f"deployed {pages} pages to Cloudflare Pages project '{CF_PROJECT}'")
    if url:
        print(f"  {url}")
    return url
