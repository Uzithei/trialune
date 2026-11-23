"""Local purchasing-agent release gate and legacy engineering fixture command."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from eval_orchestrator.adapters.bundle import json_bytes, read_bundle, render_html, write_bundle
from eval_orchestrator.adapters.fixture import FixtureAdapter
from eval_orchestrator.adapters.trace_json import parse_suite, read_input
from eval_orchestrator.application.evaluate import evaluate
from eval_orchestrator.application.release import compare_suites, evaluate_suite, exit_code
from eval_orchestrator.domain.contracts import Plan
from eval_orchestrator.domain.purchasing import Suite, Verdict


def traces(suite: Suite) -> dict[str, list[dict[str, Any]]]:
    return {case.case_id: [event.to_dict() for event in case.events] for case in suite.cases}


def audit_files(raw: bytes) -> tuple[dict[str, bytes], Verdict]:
    suite = parse_suite(raw)
    report = evaluate_suite(suite)
    data = asdict(report)
    return {
        "input.json": raw,
        "report.json": json_bytes(data),
        "report.html": render_html(data, traces(suite)),
    }, report.verdict


def comparison_files(baseline_raw: bytes, candidate_raw: bytes) -> tuple[dict[str, bytes], Verdict]:
    baseline, candidate = parse_suite(baseline_raw), parse_suite(candidate_raw)
    report = compare_suites(baseline, candidate)
    data = asdict(report)
    return {
        "baseline-input.json": baseline_raw,
        "candidate-input.json": candidate_raw,
        "report.json": json_bytes({"schema_version": 1, "kind": "comparison", **data}),
        "report.html": render_html(data["candidate"], traces(candidate), comparison=data),
    }, report.candidate.verdict


def verify_bundle(directory: Path) -> Verdict:
    mode, actual = read_bundle(directory)
    if mode == "audit":
        expected, verdict = audit_files(actual["input.json"])
    else:
        expected, verdict = comparison_files(
            actual["baseline-input.json"], actual["candidate-input.json"]
        )
    if actual != expected:
        raise ValueError(
            "Bundle does not reproduce with this evaluator (tampered or version changed)"
        )
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fixture = commands.add_parser(
        "fixture-run", help="Run the original synthetic engineering fixture"
    )
    fixture.add_argument("--fixture", required=True, type=Path)
    fixture.add_argument("--output", required=True, type=Path)
    audit = commands.add_parser("audit", help="Replay a purchasing trace corpus and gate release")
    audit.add_argument("--input", required=True, type=Path)
    audit.add_argument("--output", required=True, type=Path, help="New local evidence directory")
    compare = commands.add_parser(
        "compare", help="Re-evaluate and compare matching scenario contracts"
    )
    compare.add_argument("--baseline", required=True, type=Path)
    compare.add_argument("--candidate", required=True, type=Path)
    compare.add_argument("--output", required=True, type=Path)
    verify = commands.add_parser(
        "verify-bundle", help="Check integrity and reproduce saved results"
    )
    verify.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "audit":
            files, verdict = audit_files(read_input(args.input))
            write_bundle(args.output, "audit", files)
        elif args.command == "compare":
            files, verdict = comparison_files(read_input(args.baseline), read_input(args.candidate))
            write_bundle(args.output, "compare", files)
        elif args.command == "verify-bundle":
            verdict = verify_bundle(args.directory)
            print(f"VERIFIED: integrity and replay match; recorded release verdict: {verdict}")
            return 0
        else:
            plan = Plan("synthetic-accuracy", "1", "deterministic-fixture-v1", ("a", "b", "c"), 0.8)
            report = evaluate(plan, FixtureAdapter(args.fixture))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x") as output:
                output.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
            print(args.output)
            return 0
    except (OSError, ValueError) as exc:
        parser.exit(2, f"{args.command}: {exc}\n")
    print(f"{verdict.upper()}: {args.output / 'report.html'}")
    return exit_code(verdict)


if __name__ == "__main__":
    raise SystemExit(main())
