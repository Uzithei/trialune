import copy
import json

import pytest
from test_purchasing import document, event, good_events

from eval_orchestrator.adapters.trace_json import parse_suite
from eval_orchestrator.application.release import compare_suites, evaluate_suite, exit_code
from eval_orchestrator.domain.purchasing import Verdict


def suite(data):
    return parse_suite(json.dumps(data).encode())


def add_case(data, *, required, entries):
    case = document(entries)["cases"][0]
    case.update(case_id="second", required=required)
    data["cases"].append(case)
    return data


def test_required_failure_blocks_release_without_dropping_cases():
    data = add_case(document(), required=True, entries=[event("finished", claimed_success=True)])
    result = evaluate_suite(suite(data))
    assert result.verdict == Verdict.FAIL
    assert result.counts == {
        "total": 2,
        "required": 2,
        "pass": 1,
        "fail": 1,
        "inconclusive": 0,
        "optional_nonpassing": 0,
    }


def test_optional_failure_is_visible_but_does_not_block():
    data = add_case(document(), required=False, entries=[event("finished", claimed_success=True)])
    result = evaluate_suite(suite(data))
    assert result.verdict == Verdict.PASS
    assert result.counts["optional_nonpassing"] == 1
    assert result.cases[1].verdict == Verdict.FAIL


def test_required_missing_evidence_is_inconclusive():
    data = document(good_events()[:3])
    result = evaluate_suite(suite(data))
    assert result.verdict == Verdict.INCONCLUSIVE
    assert exit_code(result.verdict) == 3


def test_regression_is_compared_by_case_identity_and_actual_results():
    baseline = document()
    candidate = document()
    candidate["cases"][0]["events"][3]["vendor"] = "attacker"
    result = compare_suites(suite(baseline), suite(candidate))
    assert result.baseline.verdict == Verdict.PASS
    assert result.candidate.verdict == Verdict.FAIL
    assert result.changes[0].regression
    assert "EFFECT_MISMATCH" in result.changes[0].added_codes


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["policy"].update(budget_minor=99999),
        lambda d: d.update(suite_id="other"),
        lambda d: d["cases"][0].update(scenario_version="2"),
        lambda d: d["cases"][0].update(expected_orders=[]),
        lambda d: d["cases"][0].update(case_id="new-case"),
    ],
)
def test_comparison_rejects_changed_contract(change):
    before = document()
    after = copy.deepcopy(before)
    change(after)
    with pytest.raises(ValueError, match="Incomparable"):
        compare_suites(suite(before), suite(after))


def test_case_order_does_not_break_comparison():
    data = add_case(document(), required=True, entries=good_events())
    reversed_data = copy.deepcopy(data)
    reversed_data["cases"].reverse()
    result = compare_suites(suite(data), suite(reversed_data))
    assert not any(change.regression for change in result.changes)
