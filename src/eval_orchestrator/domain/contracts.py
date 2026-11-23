"""Small executable contracts for the first offline vertical slice."""

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from enum import StrEnum


class Execution(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class Assessment(StrEnum):
    MEETS = "meets_threshold"
    BELOW = "below_threshold"
    INCONCLUSIVE = "inconclusive"
    NOT_ASSESSED = "not_assessed"


@dataclass(frozen=True)
class Plan:
    """Fixture-only plan; deliberately not the complete production manifest."""

    suite: str
    suite_version: str
    target_revision: str
    sample_ids: tuple[str, ...]
    threshold: float | None = None

    def __post_init__(self) -> None:
        if not all((self.suite, self.suite_version, self.target_revision)):
            raise ValueError("Suite, version and target revision are required")
        if not isinstance(self.sample_ids, tuple):
            raise ValueError("Sample selection must be an immutable tuple")
        if not self.sample_ids or not all(isinstance(s, str) and s for s in self.sample_ids):
            raise ValueError("At least one nonempty sample ID is required")
        if len(set(self.sample_ids)) != len(self.sample_ids):
            raise ValueError("Sample IDs must be unique")
        if self.threshold is not None and not 0 <= self.threshold <= 1:
            raise ValueError("Threshold must be finite and between zero and one")

    @property
    def digest(self) -> str:
        canonical = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class Result:
    execution: Execution
    score: float | None
    scored: int
    expected: int
    error: str | None = None

    def __post_init__(self) -> None:
        if self.expected < 1 or not 0 <= self.scored <= self.expected:
            raise ValueError("Invalid sample counts")
        if self.score is not None and (not math.isfinite(self.score) or not 0 <= self.score <= 1):
            raise ValueError("Synthetic accuracy must be finite and between zero and one")
        if (self.scored == 0) != (self.score is None):
            raise ValueError("Score and scored sample count disagree")
        if self.execution == Execution.FAILED and not self.error:
            raise ValueError("Execution failure requires a reason")

    def assess(self, threshold: float | None) -> Assessment:
        if threshold is not None and not 0 <= threshold <= 1:
            raise ValueError("Invalid threshold")
        if self.execution != Execution.SUCCEEDED or self.scored != self.expected:
            return Assessment.INCONCLUSIVE
        if self.score is None:
            return Assessment.INCONCLUSIVE
        if threshold is None:
            return Assessment.NOT_ASSESSED
        return Assessment.MEETS if self.score >= threshold else Assessment.BELOW
