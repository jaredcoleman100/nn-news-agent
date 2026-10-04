"""Plugin interfaces. Hold these stable; everything domain-specific lives behind them."""
from __future__ import annotations
from typing import Any, Protocol
from .schema import Job, Context, Draft, Report


class Trigger(Protocol):
    name: str
    def to_job(self, product: dict[str, Any], payload: dict[str, Any]) -> Job: ...


class Loader(Protocol):
    name: str
    def load(self, job: Job, product: dict[str, Any]) -> Context: ...


class SourceAdapter(Protocol):
    name: str
    def fetch(self, source: dict[str, Any], since: str | None) -> list[dict[str, Any]]: ...


class EthicsCode(Protocol):
    """Deterministic. screen() never calls a model."""
    name: str
    version: str
    def screen(self, draft: Draft, product: dict[str, Any]) -> dict[str, Any]: ...
    def style(self, draft: Draft, product: dict[str, Any]) -> dict[str, Any]: ...


class ModelProvider(Protocol):
    name: str
    def draft(self, template: str, context: Context, product: dict[str, Any], revise_from: dict | None = None) -> tuple[Draft, dict[str, int]]: ...
    def memo(self, draft: Draft, screen: dict[str, Any], product: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]: ...


class Renderer(Protocol):
    name: str
    def render(self, report: Report, product: dict[str, Any]) -> tuple[str, str]: ...   # (mime, content)


class Deliverer(Protocol):
    name: str
    def deliver(self, report: Report, rendered: tuple[str, str], product: dict[str, Any]) -> str | None: ...  # receipt
