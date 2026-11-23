import json
import subprocess
import sys
from pathlib import Path

import pytest

from eval_orchestrator.adapters.fixture import FixtureAdapter
from eval_orchestrator.application.evaluate import evaluate
from eval_orchestrator.domain.contracts import Plan

ROOT = Path(__file__).resolve().parents[1]


def run_cli(fixture, output):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "eval_orchestrator.interfaces.cli",
            "fixture-run",
            "--fixture",
            str(fixture),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_real_cli_produces_repeatable_report_and_preserves_evidence(tmp_path):
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    fixture = ROOT / "fixtures/complete.json"
    assert run_cli(fixture, first).returncode == 0
    assert run_cli(fixture, second).returncode == 0
    assert first.read_bytes() == second.read_bytes()
    report = json.loads(first.read_text())
    assert report["result"]["score"] == pytest.approx(2 / 3)
    assert report["result"]["expected"] == 3
    assert report["assessment"] == "below_threshold"
    assert "synthetic" in report["scope"]
    previous = first.read_bytes()
    assert run_cli(fixture, first).returncode == 2
    assert first.read_bytes() == previous


def test_cli_partial_result_remains_inconclusive(tmp_path):
    output = tmp_path / "report.json"
    assert run_cli(ROOT / "fixtures/partial.json", output).returncode == 0
    report = json.loads(output.read_text())
    assert report["assessment"] == "inconclusive"
    assert report["result"]["scored"] == 1
    assert report["result"]["expected"] == 3


@pytest.mark.parametrize("fixture", ["malformed.json", "missing.json"])
def test_cli_bad_input_fails_without_success_report(tmp_path, fixture):
    output = tmp_path / "report.json"
    result = run_cli(ROOT / "fixtures" / fixture, output)
    assert result.returncode == 2
    assert "fixture-run:" in result.stderr
    assert not output.exists()


@pytest.mark.parametrize(
    "data",
    [
        [],
        {},
        {"schema_version": 2, "samples": []},
        {"schema_version": True, "samples": []},
        {"schema_version": 1, "samples": {}},
        {"schema_version": 1, "samples": [{"id": "a", "passed": 1}]},
        {"schema_version": 1, "samples": [{"id": "a", "passed": True}] * 2},
        {"schema_version": 1, "samples": [{"id": "unexpected", "passed": True}]},
        {"schema_version": 1, "samples": [{"id": "a"}]},
    ],
)
def test_import_rejects_ambiguous_or_wrong_protocol_data(tmp_path, data):
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        evaluate(Plan("suite", "1", "target", ("a",)), FixtureAdapter(path))


def test_empty_fixture_is_missing_evidence_not_a_pass(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text('{"schema_version": 1, "samples": []}')
    report = evaluate(Plan("suite", "1", "target", ("a",), 0.8), FixtureAdapter(path))
    assert report["assessment"] == "inconclusive"
    assert report["result"]["score"] is None
