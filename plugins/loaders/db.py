"""Loaders that read from Supabase. `hit` loads one hit + beat + related items; `window` loads all reported hits in a time window."""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from core import outlets
from core.registry import register
from core.schema import Job, Context

_SB = None
def sb():
    global _SB
    if _SB is None:
        from supabase import create_client
        _SB = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    return _SB

ITEM_FIELDS = ("id", "title", "body", "url", "published_at", "source_id", "title_en", "body_en", "lang")


def _slim(rows: list[dict]) -> list[dict]:
    return [{k: r.get(k) for k in ITEM_FIELDS} for r in rows]


WINDOW_OVERFETCH = int(os.environ.get("WINDOW_OVERFETCH", "8"))


def _in_window(item: dict[str, Any], cutoff: datetime) -> bool:
    """Is the STORY itself inside the window, rather than merely its hit row?

    `hits.created_at` is when the hit was computed, not when the story ran. The two coincide only
    in steady state. Any rebuild_hits() run - a threshold retune, an embedder switch - stamps
    surviving hits with a fresh created_at, and a 24h window then admits the whole corpus: 15 of
    the 25 items in one Nord-Norge digest were published more than a day earlier, the oldest three
    months before, and the satire desk's window reached back to January 2025. Because selection is
    `order by score desc`, staleness is not even correlated with rank. A morning brief presenting a
    June story as today's news is a factual misrepresentation, not an untidy feed.

    published_at is absent on some sources (sitemap entries, a few scholarly records), so fall back
    to fetched_at, and keep an item with neither: hits.created_at has already bounded it.
    """
    for key in ("published_at", "fetched_at"):
        raw = item.get(key)
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= cutoff
    return True


class HitLoader:
    name = "hit"
    def load(self, job: Job, product: dict[str, Any]) -> Context:
        hit = sb().table("hits").select("*").eq("id", job.payload["hit_id"]).single().execute().data
        item = sb().table("items").select("*").eq("id", hit["item_id"]).single().execute().data
        beat = sb().table("beats").select("id,name,description,ethics_profile").eq("id", hit["beat_id"]).single().execute().data
        rel = sb().rpc("related_items", {"query_embedding": item["embedding"],
                                         "days": product.get("related_days", 14), "k": 6,
                                         "newsroom": product["newsroom_id"]}).execute().data
        return Context(primary=_slim([item]), related=_slim([r for r in rel if r["id"] != item["id"]]), beat=beat,
                       meta={"hit_id": hit["id"], "score": hit["score"]})


class WindowLoader:
    name = "window"
    def load(self, job: Job, product: dict[str, Any]) -> Context:
        hours = job.payload.get("window_hours", product.get("window_hours", 24))
        # PostgREST sends filter values as literals, so a SQL expression like
        # "now() - interval '24 hours'" reaches Postgres as text and fails to cast.
        # Compute the cutoff here and send an ISO timestamp.
        cutoff_dt = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff = cutoff_dt.isoformat()
        # hits and reports are both shared across newsrooms in this project, so an unscoped
        # window pulls the rikspolitikk desk's hits into the Nord-Norge digest: measured at
        # 18 of 25 items on a 30-day window before this filter existed.
        newsroom = product["newsroom_id"]
        q = (sb().table("hits").select("id,score,beat_id,items(*)")
             .eq("newsroom_id", newsroom).gte("created_at", cutoff))
        beats = product.get("beats")
        if beats:
            q = q.in_("beat_id", beats)
        # Overfetch: the recency filter runs in Python because it needs a published_at ->
        # fetched_at fallback that PostgREST cannot express, and the top `max_items` by score
        # can otherwise be entirely stale.
        max_items = int(product.get("max_items", 25))
        # `overfetch` is a product override because a region-filtered product needs far more
        # headroom: Norwegian outlets are the large majority of hits, so a brief that excludes
        # them finds almost nothing in the top 200 by score.
        overfetch = int(product.get("overfetch", WINDOW_OVERFETCH))
        rows = q.order("score", desc=True).limit(max_items * overfetch).execute().data
        # NOT truncated to max_items here: the region filter below has to see the whole ranked
        # window, or it selects from a list that is already 90% Norwegian.
        rows = [r for r in rows if r.get("items") and _in_window(r["items"], cutoff_dt)]
        items = [{**_slim([r["items"]])[0], "beat_id": r["beat_id"], "score": r["score"]} for r in rows]
        # Name the outlet, and say whether it is this newsroom's own. The drafter previously got
        # only a `source_id` integer and had to infer the outlet from the URL host -- workable for
        # naming a source, useless for the editorial rule that NRK's own reporting is context
        # rather than the lead. Additive: the satire desk shares this loader and ignores both keys.
        srcs = {s["id"]: s for s in sb().table("sources").select("id,name,url,config").execute().data}
        for it in items:
            src = srcs.get(it.get("source_id")) or {}
            it["source"] = src.get("name") or "unknown"
            it["own"] = outlets.is_own(src)
            # Where the OUTLET sits, from sources.json. Used by the region filter below and
            # available to every template; the existing products ignore it.
            it["region"] = (src.get("config") or {}).get("region") or "global"

        # Optional region filter, so a product can be scoped to where the reporting came from.
        # `regions` keeps only those; `exclude_regions` drops them. Both are absent from the
        # existing products, which therefore behave exactly as before.
        include = product.get("regions")
        exclude = product.get("exclude_regions")
        if include:
            items = [i for i in items if i["region"] in include]
        if exclude:
            items = [i for i in items if i["region"] not in exclude]
        # Truncate AFTER filtering, still in score order -- unless the product asks for a floor
        # per region.
        #
        # `per_region_min` exists because a global top-N is the wrong rule for a brief about
        # regional spread. Asia and Europe have four times the feeds of Latin America, so they win
        # the ranking on volume rather than on scoring better: measured over a 7-day window, Latin
        # America's mean hit score was 0.517 against Europe's 0.513 and Asia's 0.508, and it still
        # took one slot in thirty. Reserving the top few from each region first, then filling the
        # remainder by score, keeps the ranking inside a region while stopping the largest regions
        # from crowding the smallest out of the brief entirely.
        floor = int(product.get("per_region_min", 0))
        if floor:
            picked, rest = [], []
            per: dict[str, int] = {}
            for it in items:                       # already in score order
                r = it["region"]
                if per.get(r, 0) < floor:
                    per[r] = per.get(r, 0) + 1
                    picked.append(it)
                else:
                    rest.append(it)
            items = (picked + rest)[:max_items]
            # Restore global score order so the drafter still sees the strongest material first.
            items.sort(key=lambda i: -(i.get("score") or 0))
        else:
            items = items[:max_items]

        external, own = outlets.split(items)
        # reports has no beat_id; the beat is reachable only via hit_id. Keep the comment on
        # its own line: appended to the expression it swallowed .execute().data and this was
        # silently handing the drafter an unexecuted query object instead of prior reports.
        reports = (sb().table("reports").select("id,headline,gate,hit_id")
                   .eq("newsroom_id", newsroom)
                   .gte("created_at", cutoff).execute().data)
        return Context(primary=items, related=[], beat=None,
                       meta={"window_hours": hours, "prior_reports": reports,
                             # Counts, so the template can say plainly when the outside world was
                             # quiet rather than padding the lead with NRK's own stories.
                             "external_count": len(external), "own_count": len(own),
                             # How many items came from each region, so a template can say plainly
                             # which parts of the world were quiet instead of implying coverage.
                             "regions": {r: sum(1 for i in items if i["region"] == r)
                                         for r in sorted({i["region"] for i in items})},
                             "own_outlet_domains": list(outlets.OWN_DOMAINS)})


register("loader", HitLoader()); register("loader", WindowLoader())
