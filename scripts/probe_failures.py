"""Prove selected checks reject broken behavior, using disposable source copies."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBES = [
    (
        "wrong-agent-output-falsely-passes",
        "src/eval_orchestrator/domain/grading.py",
        'passed = same(actual, check["expected"])',
        "passed = True",
        "tests/test_agent_runner.py::test_external_agent_runs_and_output_is_actually_graded",
    ),
    (
        "forbidden-tool-call-ignored",
        "src/eval_orchestrator/domain/grading.py",
        'status = "fail" if violations else "pass"',
        'status = "pass"',
        "tests/test_agent_adversarial.py::test_valid_final_state_does_not_erase_forbidden_history",
    ),
    (
        "unscored-required-check-falsely-passes",
        "src/eval_orchestrator/domain/grading.py",
        'execution != "completed" or any(check["status"] != "pass" for check in required)',
        'execution != "completed"',
        "tests/test_agent_runner.py::test_manual_required_check_cannot_pass",
    ),
    (
        "revoked-approval-falsely-accepted",
        "src/eval_orchestrator/domain/replay.py",
        "if approval.revoked_by:",
        "if False and approval.revoked_by:",
        "tests/test_purchasing.py::test_revocation_blocks_request_and_commit",
    ),
    (
        "duplicate-purchase-not-detected",
        "src/eval_orchestrator/domain/replay.py",
        "if order_id in self.effects:",
        "if False and order_id in self.effects:",
        "tests/test_purchasing.py::test_retry_new_transaction_is_duplicate_effect",
    ),
    (
        "required-case-silently-dropped",
        "src/eval_orchestrator/application/release.py",
        "required = tuple(result for result in results if result.required)",
        "required = results[:1]",
        "tests/test_release.py::test_required_failure_blocks_release_without_dropping_cases",
    ),
    (
        "partial-evidence-falsely-passes",
        "src/eval_orchestrator/domain/contracts.py",
        "self.execution != Execution.SUCCEEDED or self.scored != self.expected",
        "self.execution != Execution.SUCCEEDED",
        "tests/test_contracts.py::test_incomplete_evidence_cannot_pass",
    ),
    (
        "low-score-falsely-passes",
        "src/eval_orchestrator/domain/contracts.py",
        "self.score >= threshold",
        "self.score <= threshold",
        "tests/test_contracts.py::test_low_score_is_successful_execution_not_runner_failure",
    ),
]


def main() -> int:
    for name, relative, old, new, test in PROBES:
        with tempfile.TemporaryDirectory(prefix="harness-probe-") as directory:
            scratch = Path(directory)
            shutil.copytree(ROOT / "src", scratch / "src")
            shutil.copytree(ROOT / "tests", scratch / "tests")
            shutil.copy(ROOT / "pyproject.toml", scratch)
            path = scratch / relative
            content = path.read_text()
            if content.count(old) != 1:
                print(f"FAIL {name}: mutation anchor changed; update the probe")
                return 1
            path.write_text(content.replace(old, new))
            environment = {**os.environ, "PYTHONPATH": str(scratch / "src")}
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", test],
                cwd=scratch,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            print(f"PROBE {name}\n{result.stdout}{result.stderr}")
            # Pytest 1 means test failure; collection/setup errors must not count as detection.
            if result.returncode != 1 or "AssertionError" not in result.stdout:
                print(f"FAIL {name}: expected assertion failure, got exit {result.returncode}")
                return 1
    with tempfile.TemporaryDirectory(prefix="harness-boundary-") as directory:
        scratch = Path(directory)
        shutil.copytree(ROOT / "src", scratch / "src")
        (scratch / "scripts").mkdir()
        shutil.copy(ROOT / "scripts/check_architecture.py", scratch / "scripts")
        (scratch / "src/eval_orchestrator/domain/illegal.py").write_text("import socket\n")
        result = subprocess.run(
            [sys.executable, str(scratch / "scripts/check_architecture.py")],
            capture_output=True,
            text=True,
            timeout=10,
        )
        print(f"PROBE illegal-domain-import\n{result.stdout}{result.stderr}")
        if result.returncode != 1 or "socket belongs behind an adapter" not in result.stdout:
            return 1
    print(f"All {len(PROBES) + 1} broken variants were detected; working sources unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
