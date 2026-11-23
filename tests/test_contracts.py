from dataclasses import FrozenInstanceError, replace

import pytest

from eval_orchestrator.application.evaluate import evaluate
from eval_orchestrator.domain.contracts import Assessment, Execution, Plan, Result


def test_plan_is_immutable_and_identity_tracks_execution_inputs():
    plan = Plan("suite", "1", "target-1", ("a", "b"), 0.8)
    with pytest.raises(FrozenInstanceError):
        plan.threshold = 0.1
    assert plan.digest == replace(plan).digest
    for changed in (
        replace(plan, suite_version="2"),
        replace(plan, target_revision="target-2"),
        replace(plan, sample_ids=("b", "a")),
        replace(plan, threshold=0.9),
    ):
        assert changed.digest != plan.digest


@pytest.mark.parametrize("ids", [("a", "a"), (), ["a"], ("",)])
def test_bad_sample_selections_are_rejected(ids):
    with pytest.raises(ValueError):
        Plan("suite", "1", "target", ids)


def test_low_score_is_successful_execution_not_runner_failure():
    result = Result(Execution.SUCCEEDED, 0.2, 10, 10)
    assert result.execution == Execution.SUCCEEDED
    assert result.assess(0.8) == Assessment.BELOW


@pytest.mark.parametrize("execution", list(Execution))
def test_incomplete_evidence_cannot_pass(execution):
    result = Result(
        execution, 1.0, 1, 3, "engine crashed" if execution == Execution.FAILED else None
    )
    assert result.assess(0.8) == Assessment.INCONCLUSIVE


@pytest.mark.parametrize(
    "execution", [Execution.FAILED, Execution.CANCELLED, Execution.INTERRUPTED]
)
def test_unsuccessful_execution_cannot_pass_even_with_full_scores(execution):
    result = Result(
        execution, 1.0, 3, 3, "engine crashed" if execution == Execution.FAILED else None
    )
    assert result.assess(0.8) == Assessment.INCONCLUSIVE


def test_no_threshold_means_measurement_only_and_threshold_is_inclusive():
    result = Result(Execution.SUCCEEDED, 0.8, 3, 3)
    assert result.assess(None) == Assessment.NOT_ASSESSED
    assert result.assess(0.8) == Assessment.MEETS
    assert Result(Execution.SUCCEEDED, None, 0, 3).assess(0.8) == Assessment.INCONCLUSIVE


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 1.1])
def test_invalid_scores_and_thresholds_are_rejected(value):
    with pytest.raises(ValueError):
        Result(Execution.SUCCEEDED, value, 1, 1)
    with pytest.raises(ValueError):
        Plan("suite", "1", "target", ("a",), value)
    with pytest.raises(ValueError):
        Result(Execution.SUCCEEDED, 1, 1, 1).assess(value)


@pytest.mark.parametrize(
    "score,scored,expected", [(1, 0, 1), (None, 1, 1), (1, 2, 1), (None, 0, 0)]
)
def test_invalid_denominators_are_rejected(score, scored, expected):
    with pytest.raises(ValueError):
        Result(Execution.SUCCEEDED, score, scored, expected)


def test_failure_requires_reason():
    with pytest.raises(ValueError):
        Result(Execution.FAILED, None, 0, 3)


def test_adapter_cannot_shrink_plan_denominator():
    class WrongDenominator:
        def run(self, plan):
            return Result(Execution.SUCCEEDED, 1, 1, 1)

    with pytest.raises(ValueError, match="denominator"):
        evaluate(Plan("suite", "1", "target", ("a", "b")), WrongDenominator())
