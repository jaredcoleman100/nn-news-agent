"""Typed records that flow between pipeline stages. Stages talk through these, never through each other."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Job:
    """One unit of work. Created by a trigger; consumed by the pipeline."""
    product_id: str
    newsroom_id: str
    trigger: str                      # hit | schedule | document | request
    payload: dict[str, Any]           # trigger-specific: {"hit_id":..} | {"window_hours":..} | {"path":..} | {"prompt":..}
    id: int | None = None


@dataclass
class Context:
    """Everything the drafting stage may use. Produced by a loader."""
    primary: list[dict[str, Any]]     # the item(s)/document(s) the job is about
    related: list[dict[str, Any]] = field(default_factory=list)
    beat: dict[str, Any] | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Draft:
    headline: str
    body: str
    claims: list[dict[str, Any]] = field(default_factory=list)
    sections: dict[str, str] = field(default_factory=dict)   # for templated genres


@dataclass
class Report:
    job: Job
    draft: Draft
    ethics_screen: dict[str, Any]
    style_check: dict[str, Any]
    memo: dict[str, Any]
    gate: str                          # blocked | review | clear
    revision: int
    versions: dict[str, str]           # corpus/rules/template versions used
    usage: dict[str, int]
    log: list[dict[str, Any]]
    id: int | None = None

    def to_row(self) -> dict[str, Any]:
        return {"job_id": self.job.id, "product_id": self.job.product_id, "newsroom_id": self.job.newsroom_id,
                "headline": self.draft.headline, "body": self.draft.body, "claims": self.draft.claims,
                # Bilingual genres carry the English half of the report in sections.body_en. This
                # was omitted until 2026-09-15, so the English existed only inside the sent email:
                # not queryable, not re-renderable, not auditable after the fact.
                "sections": self.draft.sections,
                "ethics_memo": self.memo, "gate": self.gate,
                "screen_result": {"ethics": self.ethics_screen, "style": self.style_check},
                "revision": self.revision, "versions": self.versions}
