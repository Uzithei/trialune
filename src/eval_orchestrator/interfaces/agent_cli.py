"""General agent evaluation CLI: execute targets, retain evidence, compare versions."""

import argparse
import hashlib
import platform
import sys
from pathlib import Path
from typing import Any

from eval_orchestrator.adapters.bundle import json_bytes
from eval_orchestrator.adapters.eval_report import comparison_html, junit, render
from eval_orchestrator.adapters.eval_store import RunStore, atomic, load_suite_file, read_json
from eval_orchestrator.adapters.process_agent import ProcessAgent
from eval_orchestrator.application.agent_eval import (
    compare_reports,
    evaluate_attempt,
    execute_suite,
    report,
)
from eval_orchestrator.domain.tasks import ENGINE, TaskSuite, integer, items, obj, parse_tasks, text

PACKS = Path(__file__).resolve().parents[1] / "packs"
EXAMPLES = Path(__file__).resolve().parents[1] / "adapters"


def manifest_for(suite: TaskSuite, runner: ProcessAgent, repeats: int, seed: int) -> dict[str, Any]:
    integer(repeats, "repeats", 1, 100)
    integer(seed, "seed", 0, 2**31 - 101)
    if repeats * len(suite.tasks) > 1000:
        raise ValueError("At most 1000 scheduled attempts per run")
    return {
        "schema_version": 1,
        "engine": ENGINE,
        "suite_sha256": suite.digest,
        "agent": runner.identity,
        "repeats": repeats,
        "seed": seed,
        "state": "running",
        "runtime": {"python": platform.python_version(), "platform": sys.platform},
    }


def validate_manifest(suite: TaskSuite, manifest: dict[str, Any]) -> None:
    obj(
        manifest,
        {
            "schema_version",
            "engine",
            "suite_sha256",
            "agent",
            "repeats",
            "seed",
            "state",
            "runtime",
        },
        set(),
        "run",
    )
    integer(manifest["schema_version"], "run version", 1, 1)
    if manifest["engine"] != ENGINE or manifest["suite_sha256"] != suite.digest:
        raise ValueError("Run definition/evaluator does not match current implementation")
    integer(manifest["repeats"], "repeats", 1, 100)
    integer(manifest["seed"], "seed", 0, 2**31 - 101)
    if len(suite.tasks) * manifest["repeats"] > 1000:
        raise ValueError("Too many attempts")
    if not isinstance(manifest["state"], str) or manifest["state"] not in {
        "running",
        "interrupted",
        "complete",
    }:
        raise ValueError("Invalid run state")
    obj(
        manifest["agent"],
        {"entrypoint", "sha256", "forwarded_env_names", "dependency_scope"},
        set(),
        "agent identity",
    )
    obj(manifest["runtime"], {"python", "platform"}, set(), "runtime")
    for value in manifest["runtime"].values():
        text(value, "runtime value", 100)
    agent = manifest["agent"]
    text(agent["entrypoint"], "entrypoint", 255)
    digest = text(agent["sha256"], "agent hash", 64)
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("Invalid agent hash")
    text(agent["dependency_scope"], "dependency scope", 1000)
    names = items(agent["forwarded_env_names"], "forwarded environment", 100)
    if any(not isinstance(name, str) or not name.isidentifier() for name in names):
        raise ValueError("Invalid environment names")
    if len(names) != len(set(names)):
        raise ValueError("Duplicate environment names")


def finish(
    store: RunStore, suite: TaskSuite, manifest: dict[str, Any], runner: ProcessAgent
) -> dict[str, Any]:
    try:
        result = execute_suite(suite, manifest, runner, store)
        store.write("report.json", json_bytes(result))
        store.write("report.html", render(result))
        store.write("junit.xml", junit(result))
        manifest["state"] = "complete"
        store.write("run.json", json_bytes(manifest))
        store.seal()
        return result
    except BaseException:
        manifest["state"] = "interrupted"
        store.write("run.json", json_bytes(manifest))
        raise


def run(
    suite_path: Path,
    agent_path: Path,
    output: Path,
    repeats: int = 1,
    seed: int = 0,
    forwarded_env: tuple[str, ...] = (),
) -> dict[str, Any]:
    suite = parse_tasks(load_suite_file(suite_path))
    runner = ProcessAgent(agent_path, forwarded_env)
    manifest = manifest_for(suite, runner, repeats, seed)
    with RunStore(output, create=True) as store:
        store.initialize(suite.spec, manifest)
        return finish(store, suite, manifest, runner)


def verify_store(store: RunStore) -> dict[str, Any]:
    store.check_integrity()
    suite = parse_tasks(load_suite_file(store.directory / "suite.json"))
    manifest = read_json(store.directory / "run.json")
    validate_manifest(suite, manifest)
    if manifest["state"] != "complete":
        raise ValueError("Run is not complete; use resume")
    expected_files = {
        "suite.json",
        "run.json",
        "report.json",
        "report.html",
        "junit.xml",
        "integrity.json",
        "run.lock",
    }
    attempts = []
    slot = 0
    for task in suite.tasks:
        for trial in range(manifest["repeats"]):
            expected_files |= {f"attempts/{slot:06d}.json", f"attempts/{slot:06d}.started.json"}
            marker = read_json(store.directory / "attempts" / f"{slot:06d}.started.json")
            if marker != {"slot": slot, "state": "started"}:
                raise ValueError("Invalid started marker")
            saved = store.load(slot)
            if saved is None:
                raise ValueError("Missing trial")
            recomputed = evaluate_attempt(task, trial, saved["observation"])
            if recomputed != saved:
                raise ValueError("Saved evaluation does not reproduce")
            attempts.append(recomputed)
            slot += 1
    actual_files = {
        str(p.relative_to(store.directory)) for p in store.directory.rglob("*") if p.is_file()
    }
    if actual_files != expected_files:
        raise ValueError("Unexpected files in completed run")
    recomputed_report = report(suite, manifest, attempts)
    for name, raw in (
        ("report.json", json_bytes(recomputed_report)),
        ("report.html", render(recomputed_report)),
        ("junit.xml", junit(recomputed_report)),
    ):
        if (store.directory / name).read_bytes() != raw:
            raise ValueError(f"Derived artifact does not reproduce: {name}")
    return recomputed_report


def verify(directory: Path) -> dict[str, Any]:
    if (directory / "comparison.json").exists():
        return verify_comparison(directory)
    with RunStore(directory) as store:
        return verify_store(store)


def resume(directory: Path, agent_path: Path) -> dict[str, Any]:
    runner = ProcessAgent(agent_path)
    with RunStore(directory) as store:
        suite = parse_tasks(load_suite_file(store.directory / "suite.json"))
        manifest = read_json(store.directory / "run.json")
        validate_manifest(suite, manifest)
        if manifest["agent"]["forwarded_env_names"]:
            raise ValueError("Resume with forwarded environment is unsupported; start a fresh run")
        if runner.identity != manifest["agent"]:
            raise ValueError("Resume requires the exact same agent entrypoint")
        if manifest["runtime"] != {"python": platform.python_version(), "platform": sys.platform}:
            raise ValueError("Resume requires the same runtime")
        if manifest["state"] == "complete":
            return verify_store(store)
        return finish(store, suite, manifest, runner)


def compare(baseline: Path, candidate: Path, output: Path) -> dict[str, Any]:
    snapshots = []
    for directory in (baseline, candidate):
        with RunStore(directory) as store:
            snapshots.append(
                (
                    verify_store(store),
                    read_json(directory / "suite.json"),
                    read_json(directory / "run.json"),
                )
            )
    before, after = snapshots[0][0], snapshots[1][0]
    comparison = compare_reports(before, after)
    output.mkdir(parents=True, exist_ok=False)
    # Keep full input reports, so the numeric comparison can be independently inspected.
    files = {
        "baseline-report.json": json_bytes(before),
        "candidate-report.json": json_bytes(after),
        "comparison.json": json_bytes(comparison),
        "comparison.html": comparison_html(comparison),
    }
    for prefix, (_, definition, manifest) in zip(("baseline", "candidate"), snapshots, strict=True):
        files[f"{prefix}-suite.json"] = json_bytes(definition)
        files[f"{prefix}-run.json"] = json_bytes(manifest)
    for name, raw in files.items():
        atomic(output / name, raw)
    atomic(
        output / "integrity.json",
        json_bytes(
            {
                "schema_version": 1,
                "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()},
            }
        ),
    )
    return comparison


def verify_comparison(directory: Path) -> dict[str, Any]:
    with RunStore(directory) as store:
        store.check_integrity()
        expected = {"comparison.json", "comparison.html", "integrity.json", "run.lock"}
        reports = []
        for prefix in ("baseline", "candidate"):
            expected |= {f"{prefix}-{name}.json" for name in ("suite", "run", "report")}
            suite = parse_tasks(load_suite_file(directory / f"{prefix}-suite.json"))
            manifest = read_json(directory / f"{prefix}-run.json")
            validate_manifest(suite, manifest)
            if manifest["state"] != "complete":
                raise ValueError("Comparison source is incomplete")
            saved = read_json(directory / f"{prefix}-report.json")
            tasks = {task.task_id: task for task in suite.tasks}
            attempts = [
                evaluate_attempt(tasks[a["task_id"]], a["trial"], a["observation"])
                for a in saved["attempts"]
            ]
            recomputed = report(suite, manifest, attempts)
            if saved != recomputed:
                raise ValueError("Comparison source report does not reproduce")
            reports.append(recomputed)
        if {str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file()} != expected:
            raise ValueError("Unexpected comparison files")
        result = compare_reports(*reports)
        if (directory / "comparison.json").read_bytes() != json_bytes(result):
            raise ValueError("Comparison does not reproduce")
        if (directory / "comparison.html").read_bytes() != comparison_html(result):
            raise ValueError("Comparison HTML does not reproduce")
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("packs", help="List bundled, synthetic starter packs")
    init = commands.add_parser(
        "init", help="Copy starter pack and reference agents to a new directory"
    )
    init.add_argument("directory", type=Path)
    validate = commands.add_parser("validate", help="Validate tasks without executing an agent")
    validate.add_argument("suite", type=Path)
    execute = commands.add_parser("run", help="Run a trusted local Python agent")
    execute.add_argument("--suite", type=Path, required=True)
    execute.add_argument("--agent", type=Path, required=True)
    execute.add_argument("--output", type=Path, required=True)
    execute.add_argument("--repeats", type=int, default=1)
    execute.add_argument("--seed", type=int, default=0)
    execute.add_argument(
        "--env", action="append", default=[], help="Explicit environment variable name to forward"
    )
    continuing = commands.add_parser(
        "resume", help="Continue unstarted trials; interrupted trials remain visible"
    )
    continuing.add_argument("directory", type=Path)
    continuing.add_argument("--agent", type=Path, required=True)
    inspection = commands.add_parser(
        "verify", help="Verify hashes, tool replay and grading without running agents"
    )
    inspection.add_argument("directory", type=Path)
    comparison = commands.add_parser("compare", help="Compare two verified compatible runs")
    comparison.add_argument("--baseline", type=Path, required=True)
    comparison.add_argument("--candidate", type=Path, required=True)
    comparison.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "packs":
            for path in sorted(PACKS.glob("*.json")):
                suite = parse_tasks(load_suite_file(path))
                print(f"{path.name}: {len(suite.tasks)} tasks (synthetic qualification)")
            return 0
        if args.command == "init":
            args.directory.mkdir(parents=True, exist_ok=False)
            for path in sorted(PACKS.glob("*.json")):
                atomic(args.directory / path.name, path.read_bytes())
            for name in ("reference_good", "reference_broken", "reference_refusal"):
                atomic(args.directory / f"{name}.py", (EXAMPLES / f"{name}.py").read_bytes())
            print(f"Created local starter tasks and reference agents: {args.directory}")
            return 0
        if args.command == "validate":
            suite = parse_tasks(load_suite_file(args.suite))
            print(f"VALID: {len(suite.tasks)} tasks; SHA-256 {suite.digest}")
            return 0
        if args.command == "run":
            result = run(
                args.suite, args.agent, args.output, args.repeats, args.seed, tuple(args.env)
            )
        elif args.command == "resume":
            result = resume(args.directory, args.agent)
        elif args.command == "verify":
            result = verify(args.directory)
            print(f"VERIFIED: integrity/replay match; recorded verdict {result['verdict']}")
            return 0
        else:
            result = compare(args.baseline, args.candidate, args.output)
        print(f"{result['verdict'].upper()}: {getattr(args, 'output', None) or args.directory}")
        return {"pass": 0, "fail": 1, "inconclusive": 3}[result["verdict"]]
    except KeyboardInterrupt:
        print("Interrupted; saved terminal attempts remain available for resume", file=sys.stderr)
        return 130
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        print(f"{args.command}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
