"""Which sources are the newsroom's own, and which are outside it.

This desk is NRK's. NRK's own reporting is therefore not the product -- the editor has already
seen it, or can. What earns a place in a digest is what the *other* outlets are carrying that
bears on Norway: Altaposten, iTromsø, Ávvir, SVT Sápmi, SeverPost, High North News, the Barents
Observer, SSB. NRK's own stories still belong in the brief, but as context and overlap ("we
already have this"), not as the lead.

Classification is derived from the URL host rather than stored in a column, deliberately:

  * `sources.json` is a superset of the database and authoritative for intent, while the database
    is authoritative for what is running (see supabase/SHARED-DATABASE.md). A new column has to be
    merged into both by hand, and a source added to one and not the other then silently classifies
    wrong. A host check cannot drift out of sync with itself.
  * `sources.config` already exists as jsonb, so a source that needs an explicit answer can carry
    one without a migration.

To mark a source by hand, set `config.own` to true or false; it wins over the host check.
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

# Hosts belonging to this newsroom. Override with OWN_DOMAINS="nrk.no,example.no".
OWN_DOMAINS = tuple(d.strip().lower() for d in
                    os.environ.get("OWN_DOMAINS", "nrk.no").split(",") if d.strip())


def is_own(source: dict[str, Any] | None) -> bool:
    """True when this source is the newsroom's own outlet."""
    if not source:
        return False
    explicit = (source.get("config") or {}).get("own")
    if explicit is not None:
        return bool(explicit)
    host = (urlparse(str(source.get("url") or "")).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in OWN_DOMAINS)


def org_of(source: dict[str, Any] | None) -> str:
    """Stable token for front matter and the archive index filter."""
    return "own" if is_own(source) else "external"


def split(items: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """(external, own) — external first, because it is the half that leads the digest."""
    own = [i for i in items if i.get("own")]
    external = [i for i in items if not i.get("own")]
    return external, own
