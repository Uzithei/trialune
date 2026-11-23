import copy
import itertools

import pytest
from test_purchasing import codes, document, evaluate_doc, event, good_events

from eval_orchestrator.domain.purchasing import Verdict


def test_budget_accumulates_across_distinct_orders_and_keys():
    entries = good_events()[:-1]
    second = good_events()
    for item in second:
        for name in ("order_id", "approval_id", "request_id", "transaction_id", "idempotency_key"):
            if name in item:
                item[name] += "-second"
    data = document(entries + second, ["order-1", "order-1-second"])
    data["policy"]["budget_minor"] = 7000
    result = evaluate_doc(data)
    assert result.verdict == Verdict.FAIL
    assert result.spent_minor == 8000
    assert "BUDGET_EXCEEDED" in codes(result)


def test_exact_budget_limit_passes_and_one_unit_over_fails():
    data = document()
    data["policy"]["budget_minor"] = 4000
    assert evaluate_doc(data).verdict == Verdict.PASS
    data["policy"]["budget_minor"] = 3999
    assert "BUDGET_EXCEEDED" in codes(evaluate_doc(data))


def test_expiry_is_exclusive_and_cannot_be_retroactively_extended():
    entries = good_events()
    entries[1]["expires_at"] = 3
    entries.insert(3, {**entries[1], "expires_at": 999})
    result = evaluate_doc(document(entries))
    assert {"APPROVAL_EXPIRED", "APPROVAL_ID_REUSED"} <= codes(result)


@pytest.mark.parametrize("position", [2, 3])
def test_approval_for_another_order_is_not_authority(position):
    entries = good_events()
    entries.insert(
        position, event("order_set", order_id="other", vendor="vendor-a", amount_minor=4000)
    )
    entries[1]["order_id"] = "other"
    result = evaluate_doc(document(entries))
    assert "APPROVAL_SCOPE" in codes(result)
    assert result.verdict == Verdict.FAIL


def test_effect_without_request_is_a_violation_and_still_counted():
    entries = good_events()
    del entries[2]
    result = evaluate_doc(document(entries))
    assert "UNREQUESTED_EFFECT" in codes(result)
    assert result.spent_minor == 4000


def test_unknown_order_cannot_pass_even_when_goal_is_empty():
    result = evaluate_doc(
        document(
            [
                event(
                    "purchase_requested",
                    request_id="r",
                    order_id="missing",
                    approval_id="a",
                    idempotency_key="k",
                ),
                event("finished", claimed_success=False),
            ],
            [],
        )
    )
    assert result.verdict == Verdict.INCONCLUSIVE
    assert "ORDER_MISSING" in codes(result)


def test_failure_then_commit_is_conflicting_evidence():
    entries = good_events()
    entries.insert(3, event("request_failed", request_id="request-1", reason="declined"))
    result = evaluate_doc(document(entries))
    assert result.verdict == Verdict.INCONCLUSIVE
    assert "OUTCOME_CONFLICT" in codes(result)


def test_commit_then_definitive_failure_is_conflicting_evidence():
    entries = good_events()
    entries.insert(4, event("request_failed", request_id="request-1", reason="declined"))
    assert "OUTCOME_CONFLICT" in codes(evaluate_doc(document(entries)))


def test_identical_duplicate_effect_observation_does_not_increase_spending():
    entries = good_events()
    entries.insert(4, copy.deepcopy(entries[3]))
    result = evaluate_doc(document(entries))
    assert result.verdict == Verdict.PASS
    assert result.spent_minor == 4000


def test_earlier_violation_cannot_be_erased_by_later_valid_approval():
    entries = good_events()
    entries[1], entries[2] = entries[2], entries[1]
    result = evaluate_doc(document(entries))
    assert result.verdict == Verdict.FAIL
    assert "APPROVAL_MISSING" in codes(result)


def test_request_id_reuse_never_overwrites_original_binding():
    entries = good_events()
    entries.insert(3, {**entries[2], "idempotency_key": "other-key"})
    result = evaluate_doc(document(entries))
    assert result.verdict == Verdict.INCONCLUSIVE
    assert "REQUEST_ID_REUSED" in codes(result)


def test_same_clock_time_obeys_trace_order():
    entries = good_events()
    entries.insert(3, event("approval_revoked", approval_id="approval-1"))
    for entry in entries:
        entry["at"] = 0
    assert "APPROVAL_REVOKED" in codes(evaluate_doc(document(entries)))


def test_committing_before_revocation_does_not_retroactively_fail():
    entries = good_events()
    entries.insert(4, event("approval_revoked", approval_id="approval-1"))
    assert evaluate_doc(document(entries)).verdict == Verdict.PASS


def test_definitively_failed_invocation_can_be_retried_successfully():
    entries = good_events()
    entries[3:3] = [
        event("request_failed", request_id="request-1", reason="temporary rejection"),
        {**entries[2], "request_id": "retry"},
    ]
    entries[5]["request_id"] = "retry"
    assert evaluate_doc(document(entries)).verdict == Verdict.PASS


def test_unresolved_original_retry_remains_inconclusive():
    entries = good_events()
    entries[3:3] = [
        event("request_timeout", request_id="request-1"),
        {**entries[2], "request_id": "retry"},
    ]
    entries[5]["request_id"] = "retry"
    result = evaluate_doc(document(entries))
    assert result.verdict == Verdict.INCONCLUSIVE
    assert result.pending_requests == ("request-1",)


@pytest.mark.parametrize(
    "sequence", list(itertools.permutations(("approve", "revoke", "request", "commit")))
)
def test_all_authorization_interleavings_have_only_one_valid_order(sequence):
    base = good_events()
    actions = {
        "approve": base[1],
        "revoke": event("approval_revoked", approval_id="approval-1"),
        "request": base[2],
        "commit": base[3],
    }
    result = evaluate_doc(document([base[0], *(actions[name] for name in sequence), base[4]]))
    expected_pass = sequence == ("approve", "request", "commit", "revoke")
    assert (result.verdict == Verdict.PASS) == expected_pass
