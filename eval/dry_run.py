"""End-to-end dry run with the fake provider and stdout deliverer — no network, no keys.
    PYTHONPATH=. python eval/dry_run.py
"""
from __future__ import annotations
import json
from core import pipeline, registry
from core.products import load_product
from core.schema import Job

registry.load_all()

# product with test plugins substituted
p = load_product("nord-norge", "regional-monitor")
p.update({"provider": "fake", "loader": "inline", "deliverers": [{"name": "stdout"}]})

job = Job(product_id=p["id"], newsroom_id=p["newsroom_id"], trigger="request", payload={"items": [{
    "title": "Ung mann siktet etter dødsulykke i Kautokeino",
    "body": "En 17 år gammel gutt fra Kautokeino er siktet etter en ulykke med snøscooter. Ifølge en kilde på Facebook var han beruset. Politiet bekrefter at 1 person omkom.",
    "url": "https://example.test/sak", "published_at": "2026-09-13T08:00:00Z"}]})

r = pipeline.run(job, p)
print("\n---")
print(json.dumps({"gate": r.gate, "revision": r.revision, "flags": [f["flag"] for f in r.memo["flags"]],
                  "style": [h["rule"] for h in r.style_check["rule_hits"] + r.style_check["place_name_hits"]],
                  "versions": r.versions, "log": r.log}, ensure_ascii=False, indent=1))
