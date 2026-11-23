"""Strict, versioned synthetic fixture reader. Does not imitate Inspect or garak."""

import json
from pathlib import Path

from eval_orchestrator.domain.contracts import Execution, Plan, Result


class FixtureAdapter:
    def __init__(self, path: Path) -> None:
        self.path = path

    def run(self, plan: Plan) -> Result:
        data = json.loads(self.path.read_text())
        if not isinstance(data, dict) or set(data) != {"schema_version", "samples"}:
            raise ValueError("Expected fixture schema_version and samples only")
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ValueError("Unsupported fixture schema version")
        samples = data["samples"]
        if not isinstance(samples, list):
            raise ValueError("Fixture samples must be a list")
        outcomes: dict[str, bool | None] = {}
        for sample in samples:
            if not isinstance(sample, dict) or set(sample) != {"id", "passed"}:
                raise ValueError("Each sample needs id and passed only")
            key, passed = sample["id"], sample["passed"]
            if not isinstance(key, str) or not key or key in outcomes:
                raise ValueError("Sample IDs must be nonempty and unique")
            if passed is not None and type(passed) is not bool:
                raise ValueError("Sample passed must be boolean or null (unscored)")
            outcomes[key] = passed
        if set(outcomes) - set(plan.sample_ids):
            raise ValueError("Fixture contains samples outside saved plan")
        scores = [outcomes[key] for key in plan.sample_ids if outcomes.get(key) is not None]
        return Result(
            execution=Execution.SUCCEEDED,
            score=sum(value is True for value in scores) / len(scores) if scores else None,
            scored=len(scores),
            expected=len(plan.sample_ids),
        )
