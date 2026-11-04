"""Keep `vendor/norlit-outbox` level with norlit's live outbox.

WHY THIS EXISTS

site/_data/norlit.js reads norlit's outbox directly when that repo sits beside this one on the
shared drive, and falls back to the committed snapshot under `vendor/` when it does not. A GitHub
Actions runner clones this repo and nothing else, so EVERY cloud build reads the snapshot. A piece
norlit has published therefore reaches the public site only once the snapshot carries it *in git*.

Nothing enforced that. norlit submitted «To kyster, ett vær» with `gate: publish` on 2026-11-03;
the snapshot held 26 of the live outbox's 27 pieces; the cloud build of 2026-11-04 07:49 published
the magazine without it, and the magazine index gave no sign a piece was missing. The same thing
had already happened on 2026-10-28 with three pieces. The only detector was a `console.warn` in
norlit.js, in the log of a build nobody reads, on the one machine that can see both directories.

norlit cannot fix this from its side: INTEGRATION.md grants it exactly one write, its own outbox.
The snapshot is this repo's file, so keeping it current is this repo's job -- which is why the
copy happens here and is called from `core.publish.build()` before Eleventy runs.

WHAT IT DOES NOT DO

It copies; it never deletes. A piece withdrawn from the live outbox stays in the snapshot until
someone removes it deliberately. The failure worth preventing is a published piece going missing
from the site, not a stale file sitting unread in `vendor/`.

It does not push. `--commit` writes a commit and stops there, because a push publishes.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "vendor" / "norlit-outbox"


def live_outbox() -> Path | None:
    """norlit's live outbox, or None when this machine cannot see it (any CI runner).

    Same resolution order as site/_data/norlit.js and plugins/loaders/db.py::_norlit_outbox, minus
    the snapshot itself -- the snapshot is this function's destination, never its source. Guarding
    on that matters because NORLIT_OUTBOX is allowed to point anywhere, including at `vendor/`,
    and a copy from a directory onto itself would report success while syncing nothing.
    """
    for cand in (os.environ.get("NORLIT_OUTBOX"),
                 ROOT.parent / "norlit" / "outbox"):
        if not cand:
            continue
        p = Path(cand)
        if p.is_dir() and p.resolve() != SNAPSHOT.resolve():
            return p
    return None


def missing() -> list[str]:
    """Outbox files the snapshot does not have, sorted. Empty when the live outbox is not visible:
    a machine that cannot see it has nothing to say about whether the snapshot is behind."""
    box = live_outbox()
    if not box:
        return []
    have = {f.name for f in SNAPSHOT.glob("*.json")} if SNAPSHOT.is_dir() else set()
    return sorted(f.name for f in box.glob("*.json") if f.name not in have)


def sync(quiet: bool = False) -> list[str]:
    """Copy every missing piece into the snapshot. Returns what was copied."""
    box = live_outbox()
    if not box:
        return []
    names = missing()
    if not names:
        return []
    SNAPSHOT.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copy2(box / name, SNAPSHOT / name)
    if not quiet:
        print(f"  norlit: copied {len(names)} piece(s) into vendor/norlit-outbox:")
        for name in names:
            print(f"    {name}")
        print("    COMMIT THEM, or the next cloud build publishes without them.")
    return names


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def commit() -> bool:
    """Commit the snapshot if it has uncommitted changes. Returns whether a commit was made.

    Scoped to `vendor/norlit-outbox` with an explicit pathspec: this runs unattended from a build,
    and the working tree on the shared drive routinely holds unrelated half-finished work that
    must not be swept into a commit nobody wrote.
    """
    staged = _git("add", "--", str(SNAPSHOT.relative_to(ROOT)))
    if staged.returncode != 0:
        print(f"  norlit: git add failed: {staged.stderr.strip()[:200]}")
        return False
    if not _git("diff", "--cached", "--quiet", "--",
                str(SNAPSHOT.relative_to(ROOT))).returncode:
        return False                      # nothing staged: the snapshot was already current
    names = _git("diff", "--cached", "--name-only", "--",
                 str(SNAPSHOT.relative_to(ROOT))).stdout.split()
    body = ("vendor: sync the norlit outbox snapshot\n\n"
            "The cloud build reads vendor/norlit-outbox, not norlit's live outbox, so a piece\n"
            "reaches the public site only once the snapshot carries it in git. Synced by\n"
            "core/sync_norlit.py.\n\n"
            + "\n".join(f"  {Path(n).name}" for n in names)
            + "\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>\n")
    made = _git("commit", "-m", body)
    if made.returncode != 0:
        print(f"  norlit: git commit failed: {made.stderr.strip()[:200]}")
        return False
    print(f"  norlit: committed {len(names)} snapshot file(s); push to publish them")
    return True


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--check" in argv:
        names = missing()
        if not live_outbox():
            print("norlit: live outbox not visible from here; nothing to check")
            return 0
        if names:
            print(f"norlit: vendor/norlit-outbox is behind by {len(names)} piece(s):")
            for name in names:
                print(f"  {name}")
            return 1
        print("norlit: vendor/norlit-outbox is level with the live outbox")
        return 0
    copied = sync()
    if not copied:
        print("norlit: nothing to sync")
    if "--commit" in argv:
        commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
