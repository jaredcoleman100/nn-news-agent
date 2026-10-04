"""Name → plugin lookup. Plugins register themselves on import."""
from __future__ import annotations
import importlib, pkgutil
from typing import Any

_REG: dict[str, dict[str, Any]] = {k: {} for k in ("trigger", "loader", "source", "code", "provider", "renderer", "deliverer")}


def register(kind: str, obj: Any) -> Any:
    _REG[kind][obj.name] = obj
    return obj


def get(kind: str, name: str) -> Any:
    if not _REG[kind]:
        load_all()
    try:
        return _REG[kind][name]
    except KeyError:
        raise KeyError(f"no {kind} plugin named {name!r}; have {sorted(_REG[kind])}") from None


def load_all() -> None:
    import plugins
    for pkg in pkgutil.iter_modules(plugins.__path__):
        sub = importlib.import_module(f"plugins.{pkg.name}")
        for m in pkgutil.iter_modules(sub.__path__):
            importlib.import_module(f"plugins.{pkg.name}.{m.name}")
