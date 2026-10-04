"""A product = trigger + loader + template + ethics profile + renderer + deliverer, as JSON."""
from __future__ import annotations
import json, os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = Path(os.environ.get("CONFIG_ROOT", ROOT / "config"))
TEMPLATES = ROOT / "templates"

REQUIRED = {"id", "newsroom_id", "trigger", "loader", "template", "ethics", "renderer", "deliverers"}
NON_NEGOTIABLE = {"gate_required": True, "memo_required": True, "ai_marking_required": True, "publishes": False}


def load_product(newsroom_id: str, product_id: str) -> dict[str, Any]:
    p = CONFIG_ROOT / newsroom_id / "products" / f"{product_id}.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    missing = REQUIRED - d.keys()
    if missing:
        raise ValueError(f"product {product_id}: missing {sorted(missing)}")
    for k, v in NON_NEGOTIABLE.items():
        if d.get(k, v) != v:
            raise ValueError(f"product {product_id}: {k} may not be {d[k]!r} — this is not a per-product option")
    d.update(NON_NEGOTIABLE)
    d["_template_text"] = (TEMPLATES / f"{d['template']}.md").read_text(encoding="utf-8")
    d["_config_dir"] = str(CONFIG_ROOT / newsroom_id)
    return d


def list_products(newsroom_id: str) -> list[str]:
    return sorted(p.stem for p in (CONFIG_ROOT / newsroom_id / "products").glob("*.json"))


def list_newsrooms() -> list[str]:
    return sorted(d.name for d in CONFIG_ROOT.iterdir() if (d / "products").is_dir())


def find_newsroom(product_id: str) -> str:
    """Which newsroom owns this product.

    The engine grew up single-newsroom, so every entrypoint used to take the newsroom from a
    module-level `NEWSROOM_ID` read at import. With two newsrooms that silently resolves a product
    against the wrong one — `load_product('nord-norge', 'satire-desk')` raises FileNotFoundError,
    which is the good case; a product id that exists in both would have loaded the wrong config
    without complaint. Resolve from the id itself and there is nothing to get out of sync.
    """
    owners = [n for n in list_newsrooms() if (CONFIG_ROOT / n / "products" / f"{product_id}.json").exists()]
    if not owners:
        raise FileNotFoundError(f"no newsroom defines product {product_id!r}; "
                                f"looked in {', '.join(list_newsrooms()) or '(no newsrooms)'}")
    if len(owners) > 1:
        raise ValueError(f"product {product_id!r} is defined in {owners}; pass newsroom_id explicitly")
    return owners[0]


def resolve_product(product_id: str, newsroom_id: str | None = None) -> dict[str, Any]:
    """load_product, but the newsroom is optional: derived from the product when not given."""
    return load_product(newsroom_id or find_newsroom(product_id), product_id)


def products_with_trigger(newsroom_id: str, trigger: str) -> list[str]:
    """Product ids in this newsroom answering to `trigger`. Reads the raw JSON rather than going
    through load_product, so asking the question cannot fail on an unrelated product's missing
    template — a routing lookup must not be able to break on a product it is not selecting."""
    out = []
    for p in (CONFIG_ROOT / newsroom_id / "products").glob("*.json"):
        try:
            if json.loads(p.read_text(encoding="utf-8")).get("trigger") == trigger:
                out.append(p.stem)
        except (json.JSONDecodeError, OSError):
            continue
    return sorted(out)
