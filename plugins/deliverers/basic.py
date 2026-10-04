from __future__ import annotations
import os
from typing import Any
import httpx
from core.registry import register
from core.schema import Report


class Slack:
    name = "slack"
    def deliver(self, r: Report, rendered: tuple[str, str], product: dict[str, Any]) -> str | None:
        url = os.environ.get(product["_deliverer"].get("webhook_env", "SLACK_WEBHOOK_URL"))
        if not url:
            return "skipped: no webhook"
        resp = httpx.post(url, json={"text": rendered[1]}, timeout=15)
        return resp.headers.get("x-slack-req-id", str(resp.status_code))


class Email:
    name = "email"
    def deliver(self, r: Report, rendered: tuple[str, str], product: dict[str, Any]) -> str | None:
        """Sends via Gmail API when GMAIL_TOKEN is set; otherwise writes a queue row for the Edge Function to send."""
        to = product["_deliverer"].get("to", [])
        # Bilingual subject where the product produced an English headline. Norwegian first: it is
        # the canonical text, and it is what an editor scanning the inbox sorts and searches on.
        # Capped because a subject past ~150 chars is truncated by most clients mid-word anyway.
        en = str((r.draft.sections or {}).get("headline_en") or "").strip()
        # The gate no longer withholds anything (2026-09-28): a flagged brief publishes with an
        # ethics warning on the page. So the subject says how many flags there are rather than
        # "[BLOCKED]", which prefixed most digests, withheld nothing, and taught the reader that
        # the label meant nothing.
        flags = [f for f in (r.ethics_screen or {}).get("flags") or []
                 if f.get("severity") in ("review", "block")]
        subject = (f"[{len(flags)} etiske merknader] " if flags else "") + r.draft.headline
        if en and en != r.draft.headline:
            subject = (subject + "  /  " + en)[:150]
        try:
            from plugins.loaders.db import sb
            sb().table("outbox").insert({"to": to, "subject": subject,
                                         "mime": rendered[0], "body": rendered[1], "report_id": r.id}).execute()
            return "queued"
        except Exception as e:  # noqa: BLE001
            return f"queue failed: {e}"


class Stdout:
    name = "stdout"
    def deliver(self, r: Report, rendered: tuple[str, str], product: dict[str, Any]) -> str | None:
        print(rendered[1])
        return "printed"


for x in (Slack(), Email(), Stdout()):
    register("deliverer", x)
