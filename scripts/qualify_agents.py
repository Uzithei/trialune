"""Exercise every agent task family and retain positive, negative and unknown evidence."""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def qualify(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    logs = []

    def command(*args: str, expected: int = 0) -> None:
        invocation = [sys.executable, "-m", "eval_orchestrator.interfaces.agent_cli", *args]
        result = subprocess.run(invocation, capture_output=True, text=True, timeout=30)
        logs.append(
            {
                "command": invocation,
                "exit_code": result.returncode,
                "expected_exit_code": expected,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        (output / "qualification.json").write_text(json.dumps(logs, indent=2) + "\n")
        if result.returncode != expected:
            raise ValueError(f"Agent journey failed: {args}; {result.stdout}{result.stderr}")

    project = output / "starter"
    command("init", str(project))
    command("validate", str(project / "starter.json"))
    for name, expected in (("good", 0), ("broken", 1), ("refusal", 1)):
        destination = output / name
        command(
            "run",
            "--suite",
            str(project / "starter.json"),
            "--agent",
            str(project / f"reference_{name}.py"),
            "--output",
            str(destination),
            "--repeats",
            "2",
            expected=expected,
        )
        command("verify", str(destination))
    command(
        "compare",
        "--baseline",
        str(output / "good"),
        "--candidate",
        str(output / "broken"),
        "--output",
        str(output / "comparison"),
        expected=1,
    )
    command("verify", str(output / "comparison"))
    suite = json.loads((project / "starter.json").read_text())
    suite["tasks"] = suite["tasks"][:1]
    suite["tasks"][0]["checks"].append(
        {
            "id": "human-review",
            "kind": "manual",
            "required": True,
            "reason": "Semantic review is deliberately not automated",
        }
    )
    manual = output / "manual.json"
    manual.write_text(json.dumps(suite, indent=2) + "\n")
    command(
        "run",
        "--suite",
        str(manual),
        "--agent",
        str(project / "reference_good.py"),
        "--output",
        str(output / "unscored"),
        expected=3,
    )
    command("verify", str(output / "unscored"))
    print(f"All three task families and verdicts qualified: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    qualify(parser.parse_args().output.resolve())
