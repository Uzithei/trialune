"""Deterministic evaluators with explicit unscored semantics."""

from typing import Any

from eval_orchestrator.domain.environment import lookup, same
from eval_orchestrator.domain.tasks import Task


def grade(task: Task, observation: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for check in task.spec["checks"]:
        kind = check["kind"]
        status, message = "unscored", "Execution did not produce a completed output"
        evidence: dict[str, Any] = {}
        if kind == "manual":
            message = check["reason"]
        elif observation["execution"] in {"interrupted", "not_started"}:
            message = "No trustworthy terminal observation exists for this attempt"
        elif kind == "tool_policy":
            violations = [e["index"] for e in observation["events"] if e["policy_violation"]]
            status = "fail" if violations else "pass"
            message = (
                "Forbidden or malformed tool actions"
                if violations
                else "No observed tool-policy violations"
            )
            evidence = {"event_indices": violations}
        elif kind == "state_equals" or observation["execution"] == "completed":
            source = observation["final_state"] if kind == "state_equals" else observation["output"]
            try:
                actual = lookup(source, check["pointer"])
                if kind in {"equals", "state_equals"}:
                    passed = same(actual, check["expected"])
                elif kind in {"text_match", "answer_set"}:
                    expected = check["expected"] if kind == "answer_set" else [check["expected"]]

                    def normalize(value: str, casefold: bool = check.get("casefold", False)) -> str:
                        value = " ".join(value.split())
                        return value.casefold() if casefold else value

                    passed = isinstance(actual, str) and normalize(actual) in {
                        normalize(v) for v in expected
                    }
                else:
                    passed = (
                        isinstance(actual, list)
                        and all(isinstance(v, str) for v in actual)
                        and len(actual) == len(set(actual))
                        and set(actual) == set(check["allowed"])
                    )
                status = "pass" if passed else "fail"
                message = (
                    "Declared criterion satisfied"
                    if passed
                    else "Observed value does not satisfy criterion"
                )
                if kind == "citations":
                    message += "; reference IDs only, not semantic support"
                evidence = {"pointer": check["pointer"], "actual": actual}
            except (KeyError, IndexError, TypeError):
                status, message = "fail", f"Missing value at {check['pointer']}"
        results.append(
            {
                "id": check["id"],
                "kind": kind,
                "required": check["required"],
                "status": status,
                "message": message,
                "evidence": evidence,
            }
        )
    return results


def assessment(execution: str, checks: list[dict[str, Any]]) -> str:
    required = [check for check in checks if check["required"]]
    if any(check["status"] == "fail" for check in required):
        return "fail"
    if execution != "completed" or any(check["status"] != "pass" for check in required):
        return "inconclusive"
    return "pass"
