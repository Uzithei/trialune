"""Local Launch/Doctor/Drive/Evidence/Cleanup interface. No model or account calls."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON = str(ROOT / ".venv/bin/python")
IGNORED = {
    ".git",
    ".venv",
    ".cache",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "artifacts",
    "dist",
    "htmlcov",
    ".local",
    ".agents",
    ".codex",
    ".aws",
    ".vscode",
    ".idea",
}


def snapshot() -> dict[str, str]:
    """Hash checked source/config/docs, never environment secrets or generated outputs."""
    files = {}
    for directory, subdirectories, filenames in os.walk(ROOT):
        subdirectories[:] = sorted(name for name in subdirectories if name not in IGNORED)
        for filename in sorted(filenames):
            path = Path(directory) / filename
            relative = path.relative_to(ROOT)
            if path.is_symlink() or relative == Path("AGENTS.md"):
                continue
            if path.suffix in {
                ".py",
                ".toml",
                ".lock",
                ".json",
                ".md",
                ".yml",
                ".yaml",
            } or path.name in {
                ".python-version",
                ".gitignore",
                "LICENSE",
                ".editorconfig",
                ".gitattributes",
            }:
                files[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def doctor() -> int:
    problems = []
    if sys.version_info[:2] != (3, 12):
        problems.append("Run with the project's Python 3.12: .venv/bin/python scripts/harness.py")
    if not (ROOT / ".venv/bin/python").exists() or Path(sys.prefix) != ROOT / ".venv":
        problems.append("Use the local .venv interpreter after uv sync --locked")
    if not shutil.which("uv"):
        problems.append("Install uv locally to verify dependency lock freshness")
    if not (ROOT / "uv.lock").exists():
        problems.append("Missing uv.lock; resolve dependencies before verification")
    for package in ("pytest", "pytest-cov", "ruff", "mypy", "evaluation-orchestrator"):
        try:
            print(f"{package}: {importlib.metadata.version(package)}")
        except importlib.metadata.PackageNotFoundError:
            problems.append(f"Missing {package}; run UV_CACHE_DIR=.cache/uv uv sync --locked")
    print(f"Python: {platform.python_version()} | {sys.executable}")
    print("Offline mode: no credentials, model calls, containers or running services required")
    print("\n".join(problems) if problems else "Doctor passed")
    return bool(problems)


def check() -> int:
    if doctor():
        return 1
    evidence = ROOT / "artifacts/verification" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    evidence.mkdir(parents=True, exist_ok=False)
    before = snapshot()
    commands = [
        ("lock", ["uv", "lock", "--check", "--offline"]),
        ("environment", ["uv", "sync", "--locked", "--check", "--offline"]),
        ("lint", [PYTHON, "-m", "ruff", "check", "."]),
        ("format", [PYTHON, "-m", "ruff", "format", "--check", "."]),
        ("types", [PYTHON, "-m", "mypy"]),
        ("architecture", [PYTHON, "scripts/check_architecture.py"]),
        ("repository", [PYTHON, "scripts/check_repository.py"]),
        (
            "tests",
            [
                PYTHON,
                "-m",
                "pytest",
                "--cov",
                "--cov-report=term-missing",
                f"--cov-report=json:{evidence / 'coverage.json'}",
            ],
        ),
        ("failure-probes", [PYTHON, "scripts/probe_failures.py"]),
        (
            "package",
            [PYTHON, "scripts/qualify_package.py", "--output", str(evidence / "distribution")],
        ),
        (
            "release-journey",
            [PYTHON, "scripts/qualify_release.py", "--output", str(evidence / "release-journey")],
        ),
        (
            "agent-journey",
            [PYTHON, "scripts/qualify_agents.py", "--output", str(evidence / "agent-journey")],
        ),
    ]
    checks: list[dict[str, Any]] = []
    environment = {
        **os.environ,
        "UV_CACHE_DIR": str(ROOT / ".cache/uv"),
        "COVERAGE_FILE": str(evidence / ".coverage"),
    }
    with tempfile.TemporaryDirectory(prefix="harness-drive-") as scratch:
        report = Path(scratch) / "report.json"
        commands.append(
            (
                "drive",
                [
                    str(ROOT / ".venv/bin/eval-orchestrator"),
                    "fixture-run",
                    "--fixture",
                    "fixtures/complete.json",
                    "--output",
                    str(report),
                ],
            )
        )
        for name, command in commands:
            print(f"Checking {name}...", flush=True)
            try:
                result = subprocess.run(
                    command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=120
                )
                code, output = result.returncode, result.stdout + result.stderr
            except (OSError, subprocess.TimeoutExpired) as exc:
                code, output = 1, str(exc)
            (evidence / f"{name}.log").write_text(output)
            checks.append(
                {"name": name, "command": command, "exit_code": code, "log": f"{name}.log"}
            )
            print(f"{'PASS' if code == 0 else 'FAIL'} {name}")
            if code:
                print(output)
        if report.exists():
            shutil.copy(report, evidence / "fixture-report.json")
            shutil.copy(ROOT / "fixtures/complete.json", evidence / "fixture-input.json")
    after = snapshot()
    changed = before != after
    passed = not changed and all(item["exit_code"] == 0 for item in checks)
    summary = {
        "status": "PASS" if passed else "FAIL",
        "scope": (
            "general agent execution and legacy purchasing; synthetic qualification, no live models"
        ),
        "source_sha256": hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
        "source_files": before,
        "sources_changed_during_verification": changed,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "finished_at": datetime.now(UTC).isoformat(),
        "checks": checks,
    }
    (evidence / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"{summary['status']}: {evidence / 'summary.json'}")
    if changed:
        print("Sources changed during verification; rerun against the finished candidate")
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["doctor", "check"])
    args = parser.parse_args()
    return doctor() if args.command == "doctor" else check()


if __name__ == "__main__":
    raise SystemExit(main())
