from typing import Any
from core.registry import register
from core.schema import Job

def _mk(name):
    class T:
        pass
    T.name = name
    T.to_job = staticmethod(lambda product, payload: Job(product_id=product["id"], newsroom_id=product["newsroom_id"], trigger=name, payload=payload))
    return T()

for n in ("hit", "schedule", "document", "request"):
    register("trigger", _mk(n))
