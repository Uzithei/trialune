"""One execution and assessment path shared by all task families."""

from typing import Any, Protocol

from eval_orchestrator.domain.grading import assessment, grade
from eval_orchestrator.domain.observations import validate_observation
from eval_orchestrator.domain.tasks import ENGINE, Task, TaskSuite, integer, sha


class AgentRunner(Protocol):
    def execute(self, task: Task, trial: int, seed: int) -> dict[str, Any]: ...


class AttemptStore(Protocol):
    def load(self, slot: int) -> dict[str, Any] | None: ...
    def started(self, slot: int) -> bool: ...
    def start(self, slot: int) -> None: ...
    def save(self, slot: int, result: dict[str, Any]) -> None: ...


def execute_suite(
    suite: TaskSuite, manifest: dict[str, Any], runner: AgentRunner, store: AttemptStore
) -> dict[str, Any]:
    attempts = []
    slot = 0
    for task in suite.tasks:
        for trial in range(manifest["repeats"]):
            saved = store.load(slot)
            if saved is not None:
                result = evaluate_attempt(task, trial, saved["observation"])
                if result != saved:
                    raise ValueError("Saved attempt does not match the frozen task/evaluator")
            elif store.started(slot):
                observation = {
                    "execution": "interrupted",
                    "output": None,
                    "events": [],
                    "final_state": task.spec["environment"]["state"],
                    "duration_ms": None,
                    "tool_calls": 0,
                    "usage": None,
                    "cost": None,
                    "stderr": "",
                    "error": "Prior process stopped without a terminal observation; not retried",
                }
                result = evaluate_attempt(task, trial, observation)
                store.save(slot, result)
            else:
                store.start(slot)
                result = run_attempt(task, trial, manifest["seed"] + trial, runner)
                store.save(slot, result)
            attempts.append(result)
            slot += 1
            if saved is None and result["observation"]["execution"] == "cancelled":
                raise KeyboardInterrupt
    return report(suite, manifest, attempts)


def evaluate_attempt(task: Task, trial: int, observation: dict[str, Any]) -> dict[str, Any]:
    integer(trial, "trial", 0, 99)
    validate_observation(task, observation)
    checks = grade(task, observation)
    return {
        "task_id": task.task_id,
        "trial": trial,
        "family": task.spec["family"],
        "required": task.spec["required"],
        "observation": observation,
        "checks": checks,
        "verdict": assessment(observation["execution"], checks),
    }


def run_attempt(task: Task, trial: int, seed: int, runner: AgentRunner) -> dict[str, Any]:
    return evaluate_attempt(task, trial, runner.execute(task, trial, seed))


def report(
    suite: TaskSuite, manifest: dict[str, Any], attempts: list[dict[str, Any]]
) -> dict[str, Any]:
    expected = {
        (task.task_id, trial) for task in suite.tasks for trial in range(manifest["repeats"])
    }
    actual = [(attempt["task_id"], attempt["trial"]) for attempt in attempts]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("Missing, duplicate or unexpected trial results")
    required = [a for a in attempts if a["required"]]
    verdict = (
        "fail"
        if any(a["verdict"] == "fail" for a in required)
        else "inconclusive"
        if any(a["verdict"] != "pass" for a in required)
        else "pass"
    )
    summaries = []
    for task in suite.tasks:
        trials = [attempt for attempt in attempts if attempt["task_id"] == task.task_id]
        passed = sum(attempt["verdict"] == "pass" for attempt in trials)
        durations = [
            a["observation"]["duration_ms"]
            for a in trials
            if a["observation"]["duration_ms"] is not None
        ]
        summaries.append(
            {
                "task_id": task.task_id,
                "family": task.spec["family"],
                "trials": len(trials),
                "passed": passed,
                "pass_fraction": passed / len(trials),
                "mean_duration_ms": sum(durations) / len(durations) if durations else None,
                "observed_duration_trials": len(durations),
                "total_tool_calls": sum(a["observation"]["tool_calls"] for a in trials),
            }
        )
    return {
        "schema_version": 1,
        "engine": ENGINE,
        "suite_name": suite.spec["name"],
        "suite_sha256": suite.digest,
        "configuration_sha256": sha(
            {
                "suite": suite.digest,
                "engine": ENGINE,
                "repeats": manifest["repeats"],
                "seed": manifest["seed"],
                "runtime": manifest["runtime"],
            }
        ),
        "agent": manifest["agent"],
        "repeats": manifest["repeats"],
        "seed": manifest["seed"],
        "verdict": verdict,
        "attempts": attempts,
        "task_summary": summaries,
        "counts": {
            "total": len(attempts),
            **{
                v: sum(a["verdict"] == v for a in attempts)
                for v in ("pass", "fail", "inconclusive")
            },
        },
        "limitations": [
            "Outcomes apply to supplied tasks and checks, not universal agent safety.",
            "Reference agents are deterministic qualification examples, not model results.",
            "Token usage and cost are unknown unless separately instrumented.",
            "Worker process separation is not an adversarial-code sandbox.",
        ],
    }


def compare_reports(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    if before["configuration_sha256"] != after["configuration_sha256"]:
        raise ValueError(
            "Incompatible task, evaluator, environment, limits, seed or repetition settings"
        )
    baseline = {(a["task_id"], a["trial"]): a for a in before["attempts"]}
    changes = []
    rank = {"pass": 0, "inconclusive": 1, "fail": 2}
    for attempt in after["attempts"]:
        old = baseline[(attempt["task_id"], attempt["trial"])]
        old_failures = {c["id"] for c in old["checks"] if c["status"] == "fail"}
        failures = {c["id"] for c in attempt["checks"] if c["status"] == "fail"}
        changes.append(
            {
                "task_id": attempt["task_id"],
                "trial": attempt["trial"],
                "before": old["verdict"],
                "after": attempt["verdict"],
                "regression": rank[attempt["verdict"]] > rank[old["verdict"]]
                or bool(failures - old_failures),
                "new_failures": sorted(failures - old_failures),
            }
        )
    return {
        "schema_version": 1,
        "baseline_agent": before["agent"],
        "candidate_agent": after["agent"],
        "verdict": after["verdict"],
        "changes": changes,
        "configuration_sha256": after["configuration_sha256"],
    }
