"""Slack Events API handler: reactions on a report card become editor decisions and house precedent.
Wire in Slack: Event Subscriptions → https://worker/slack/reaction, subscribe to reaction_added and message.channels
(so a threaded reply can carry the reason). Signing secret in SLACK_SIGNING_SECRET."""
from __future__ import annotations
import hashlib, hmac, os, re, time
from typing import Any

DECISIONS = {"white_check_mark": "approve", "heavy_check_mark": "approve", "pencil": "revise", "pencil2": "revise",
             "x": "kill", "no_entry_sign": "kill"}
REPORT_RE = re.compile(r"report #(\d+)")


def verify(body: bytes, ts: str, sig: str) -> bool:
    secret = os.environ.get("SLACK_SIGNING_SECRET", "")
    if not secret:
        return True
    if abs(time.time() - float(ts or 0)) > 300:
        return False
    mac = "v0=" + hmac.new(secret.encode(), f"v0:{ts}:{body.decode()}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, sig or "")


def _report_id_from_message(channel: str, ts: str) -> int | None:
    """Fetch the reacted-to message text to find 'report #N'. Needs SLACK_BOT_TOKEN with channels:history."""
    import httpx
    tok = os.environ.get("SLACK_BOT_TOKEN")
    if not tok:
        return None
    r = httpx.get("https://slack.com/api/conversations.history",
                  params={"channel": channel, "latest": ts, "inclusive": "true", "limit": 1},
                  headers={"Authorization": f"Bearer {tok}"}, timeout=10).json()
    for m in r.get("messages", []):
        mm = REPORT_RE.search(m.get("text", ""))
        if mm:
            return int(mm.group(1))
    return None


def handle(event: dict[str, Any]) -> dict[str, Any]:
    from plugins.loaders.db import sb
    kind = event.get("type")

    if kind == "reaction_added":
        decision = DECISIONS.get(event.get("reaction", ""))
        if not decision:
            return {"ignored": "reaction"}
        item = event.get("item", {})
        rid = _report_id_from_message(item.get("channel"), item.get("ts"))
        if not rid:
            return {"ignored": "no report id"}
        rep = sb().table("reports").update({"editor_decision": decision}).eq("id", rid).execute().data
        if rep:
            r = rep[0]
            memo = r.get("ethics_memo") or {}
            fact_pattern = {"flags": [f.get("flag") for f in memo.get("flags", [])],
                            "identifiers": (memo.get("identification_check") or {}).get("identifiers_used", []),
                            "gate": r.get("gate"), "product": r.get("product_id")}
            sb().table("precedent").upsert({"newsroom_id": r["newsroom_id"], "report_id": rid, "decision": decision,
                                            "fact_pattern": fact_pattern}, on_conflict="report_id").execute()
            if r.get("hit_id"):
                sb().table("hits").update({"editor_feedback": "accept" if decision == "approve" else "reject"}).eq("id", r["hit_id"]).execute()
        return {"report": rid, "decision": decision}

    if kind == "message" and event.get("thread_ts") and not event.get("bot_id"):
        # a threaded human reply on a report card = the editor's reason
        rid = _report_id_from_message(event.get("channel"), event.get("thread_ts"))
        if not rid:
            return {"ignored": "no report id"}
        reason = event.get("text", "").strip()
        sb().table("reports").update({"editor_reason": reason}).eq("id", rid).execute()
        sb().table("precedent").update({"reason": reason}).eq("report_id", rid).execute()
        return {"report": rid, "reason": "stored"}

    return {"ignored": kind}
