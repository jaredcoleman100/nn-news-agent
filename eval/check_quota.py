"""Is the Gemini key billed, and does each model in the chain answer right now?

    PYTHONPATH=. python eval/check_quota.py

Exists because the failure modes here are actively misleading. Quota exhaustion returns 429
instantly, but the provider's fallback chain then tries every other model, and some of those come
back as `503 UNAVAILABLE: this model is currently experiencing high demand` -- so a key that has
simply run out of free requests looks exactly like a provider outage. The only reliable signal is
the `quotaId` on the 429: `...-FreeTier` with `quotaValue: 20` means the key's Cloud project is
still on the free tier, whatever the billing console says. Billing enabled on a *different*
project than the one that owns the key does not move it.

One call per model, max_output_tokens=1, so running this costs a request per model and nothing else.
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
load_dotenv(Path.home() / ".config" / "nn-news-agent" / ".env")

MODELS = [m.strip() for m in os.environ.get(
    "CHECK_MODELS", "gemini-3.6-flash,gemini-2.5-flash,gemini-3.5-flash").split(",") if m.strip()]


def main() -> int:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY is not set"); return 2
    print(f"key: {len(key)} chars, prefix {key[:6]}...\n")

    from google import genai
    from google.genai import types
    client = genai.Client(api_key=key)

    free_tier = False
    for model in MODELS:
        started = time.time()
        try:
            client.models.generate_content(
                model=model, contents="ok",
                config=types.GenerateContentConfig(
                    max_output_tokens=1, http_options=types.HttpOptions(timeout=30000)))
            print(f"  {model:22} OK        {time.time() - started:5.1f}s")
        except Exception as e:  # noqa: BLE001
            text = str(e)
            quota_id = re.search(r"'quotaId': '([^']+)'", text)
            value = re.search(r"'quotaValue': '(\d+)'", text)
            code = text[:3]
            if quota_id:
                free_tier = free_tier or "FreeTier" in quota_id.group(1)
                print(f"  {model:22} {code} quota  {time.time() - started:5.1f}s  "
                      f"{quota_id.group(1)} = {value.group(1) if value else '?'}")
            else:
                print(f"  {model:22} {code}        {time.time() - started:5.1f}s  {text[:70]}")

    print()
    if free_tier:
        print("FREE TIER. The key's Cloud project is not billed -- 20 requests/day/model.")
        print("Enable billing on the project that owns THIS key, or create a key inside the")
        print("billed project and update GEMINI_API_KEY in ~/.config/nn-news-agent/.env.")
        return 1
    # NOT proof of billing. This can only detect the free tier by actually hitting its ceiling, so
    # a clean run early in the day looks identical on a billed key and an unbilled one that has
    # simply not spent its 20-per-model yet. The tell is a 429 appearing later, after ~60 requests.
    print("No quota error right now -- but this does NOT prove the key is billed: the free tier")
    print("only announces itself at its ceiling. Re-run after the day's work to be sure.")
    print("To confirm properly, open https://aistudio.google.com/apikey, note which Cloud project")
    print("owns this key, and check billing is enabled on THAT project.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
