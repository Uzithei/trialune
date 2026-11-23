"""Drive the installed CLI and retain evidence for pass/fail/unknown/comparison paths."""

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = str(ROOT / ".venv/bin/eval-orchestrator")


def qualify(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    for name, code, verdict in (
        ("baseline", 0, "pass"),
        ("candidate", 1, "fail"),
        ("incomplete", 3, "inconclusive"),
    ):
        command = [
            CLI,
            "audit",
            "--input",
            f"examples/purchasing/{name}.json",
            "--output",
            str(output / name),
        ]
        run(command, code, output / f"{name}.log")
        report = json.loads((output / name / "report.json").read_text())
        if report["verdict"] != verdict or report["counts"]["total"] != 3:
            raise ValueError(f"Unexpected {name} report: {report['verdict']}")
        run([CLI, "verify-bundle", str(output / name)], 0, output / f"{name}-verification.log")
    command = [
        CLI,
        "compare",
        "--baseline",
        "examples/purchasing/baseline.json",
        "--candidate",
        "examples/purchasing/candidate.json",
        "--output",
        str(output / "comparison"),
    ]
    run(command, 1, output / "comparison.log")
    comparison = json.loads((output / "comparison/report.json").read_text())
    if sum(change["regression"] for change in comparison["changes"]) != 2:
        raise ValueError("Expected two deliberately introduced regressions")
    run(
        [CLI, "verify-bundle", str(output / "comparison")],
        0,
        output / "comparison-verification.log",
    )
    print(f"Qualified pass/fail/inconclusive/comparison and four bundle replays: {output}")


def run(command: list[str], expected_code: int, log: Path) -> None:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
    log.write_text(
        json.dumps(
            {
                "command": command,
                "expected_exit_code": expected_code,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
            indent=2,
        )
        + "\n"
    )
    if result.returncode != expected_code:
        raise ValueError(f"Expected exit {expected_code}, got {result.returncode}; inspect {log}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    qualify(parser.parse_args().output.resolve())
