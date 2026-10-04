"""Loader for tests and ad-hoc requests: the job payload carries the content."""
from typing import Any
from core.registry import register
from core.schema import Job, Context

class InlineLoader:
    name = "inline"
    def load(self, job: Job, product: dict[str, Any]) -> Context:
        return Context(primary=job.payload.get("items", []), related=job.payload.get("related", []),
                       beat=job.payload.get("beat"), meta={"trigger": job.trigger})

register("loader", InlineLoader())
