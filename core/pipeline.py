"""The constant: load → draft → screen → style → memo → gate → (revise once) → render → deliver.
Stages are looked up by name from the product. The pipeline, not the model, owns the sequence."""
from __future__ import annotations
from typing import Any, Callable
from . import registry
from .schema import Job, Draft, Report

GATE_ORDER = {"clear": 0, "review": 1, "blocked": 2}


def run(job: Job, product: dict[str, Any], store: Callable[[Report], Report] | None = None) -> Report:
    log: list[dict[str, Any]] = []
    usage = {"input": 0, "output": 0}
    loader = registry.get("loader", product["loader"])
    code = registry.get("code", product["ethics"]["code"])
    prov = product.get("provider", "anthropic")
    if isinstance(prov, str):
        prov = {"draft": prov, "memo": prov}
    drafter = registry.get("provider", prov.get("draft", "anthropic"))
    memoist = registry.get("provider", prov.get("memo", prov.get("draft", "anthropic")))
    renderer = registry.get("renderer", product["renderer"])
    # The AI marking has to name the tool that actually drafted (NRK KI 3.3), so templates
    # carry a {ai_tool} placeholder instead of a hardcoded vendor name.
    template = product["_template_text"].replace("{ai_tool}", getattr(drafter, "label", drafter.name))

    ctx = loader.load(job, product)
    log.append({"step": "load", "primary": len(ctx.primary), "related": len(ctx.related)})

    draft, u = drafter.draft(template, ctx, product); _add(usage, u)
    log.append({"step": "draft"})

    max_rev = product.get("max_revisions", 1)
    for revision in range(1, max_rev + 2):
        screen = code.screen(draft, product)
        style = code.style(draft, product)
        log.append({"step": "screen", "gate": screen["publication_gate"], "flags": [f["flag"] for f in screen["flags"]],
                    "style": style["verdict"]})
        memo, u = memoist.memo(draft, screen, product); _add(usage, u)
        if GATE_ORDER.get(memo.get("publication_gate"), 0) < GATE_ORDER[screen["publication_gate"]]:
            memo["publication_gate"] = screen["publication_gate"]
            log.append({"step": "gate_override", "reason": "memo tried to lower gate"})
        if style["verdict"] == "fix_required" and memo["publication_gate"] == "clear":
            memo["publication_gate"] = "review"
            log.append({"step": "gate_override", "reason": "style fixes outstanding"})
        gate = memo["publication_gate"]
        if gate == "blocked" and revision <= max_rev:
            draft, u = drafter.draft(template, ctx, product, revise_from={"draft": draft, "memo": memo, "style": style}); _add(usage, u)
            log.append({"step": "revise", "n": revision})
            continue
        break

    report = Report(job=job, draft=draft, ethics_screen=screen, style_check=style, memo=memo, gate=gate,
                    revision=revision, usage=usage, log=log,
                    versions={"code": code.version, "template": product["template"], "product": product.get("version", "1"),
                              "draft_model": drafter.name, "memo_model": memoist.name,
                              # providers may fall back to another build; record what actually ran
                              "draft_model_id": getattr(drafter, "last_model", None),
                              "memo_model_id": getattr(memoist, "last_model", None)})
    if store:
        report = store(report)
    rendered: dict[str, tuple[str, str]] = {product["renderer"]: renderer.render(report, product)}
    for d in product["deliverers"]:
        rname = d.get("renderer", product["renderer"])   # email and Slack need different markup
        if rname not in rendered:
            rendered[rname] = registry.get("renderer", rname).render(report, product)
        deliverer = registry.get("deliverer", d["name"])
        receipt = deliverer.deliver(report, rendered[rname], {**product, "_deliverer": d})
        log.append({"step": "deliver", "via": d["name"], "renderer": rname, "receipt": receipt})
    return report


def _add(usage: dict[str, int], u: dict[str, int]) -> None:
    for k in usage:
        usage[k] += u.get(k, 0)
