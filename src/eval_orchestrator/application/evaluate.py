"""Execute the fixture use case without owning engine-specific behavior."""

from dataclasses import asdict
from typing import Protocol

from eval_orchestrator.domain.contracts import Plan, Result


class Adapter(Protocol):
    def run(self, plan: Plan) -> Result: ...


def evaluate(plan: Plan, adapter: Adapter) -> dict[str, object]:
    result = adapter.run(plan)
    if result.expected != len(plan.sample_ids):
        raise ValueError("Adapter denominator does not match saved plan")
    return {
        "schema_version": 1,
        "scope": "synthetic engineering fixture; not a benchmark or safety result",
        "plan": asdict(plan),
        "plan_sha256": plan.digest,
        "result": asdict(result),
        "assessment": result.assess(plan.threshold).value,
    }
