import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest
from test_agent_runner import suite_spec, task_spec

from eval_orchestrator.adapters.eval_store import RunStore, atomic
from eval_orchestrator.adapters.process_agent import ProcessAgent
from eval_orchestrator.domain.tasks import parse_tasks
from eval_orchestrator.interfaces.agent_cli import compare, manifest_for, resume, run, verify


def inputs(tmp_path):
    definition = tmp_path / "tasks.json"
    definition.write_text(json.dumps(suite_spec()))
    target = tmp_path / "agent.py"
    target.write_text('def run(context):\n    return {"total": 42, "a": 1}\n')
    return definition, target


def test_run_roundtrip_reproduces_every_derived_artifact(tmp_path):
    definition, target = inputs(tmp_path)
    output = tmp_path / "run"
    result = run(definition, target, output, repeats=2)
    assert result["counts"]["total"] == 2
    assert verify(output) == result
    tree = ET.parse(output / "junit.xml").getroot()
    assert tree.attrib["tests"] == "2"
    assert tree.attrib["errors"] == "0"


def test_completed_run_is_not_overwritten_or_reexecuted(tmp_path):
    definition, target = inputs(tmp_path)
    output = tmp_path / "run"
    run(definition, target, output)
    previous = (output / "report.json").read_bytes()
    assert resume(output, target)["verdict"] == "pass"
    assert (output / "report.json").read_bytes() == previous
    with pytest.raises(FileExistsError):
        run(definition, target, output)


def test_interrupted_slot_is_preserved_and_remaining_work_runs(tmp_path):
    definition, target = inputs(tmp_path)
    suite = parse_tasks(json.loads(definition.read_text()))
    output = tmp_path / "run"
    manifest = manifest_for(suite, ProcessAgent(target), 2, 0)
    with RunStore(output, create=True) as store:
        store.initialize(suite.spec, manifest)
        store.start(0)
    result = resume(output, target)
    assert result["counts"] == {"total": 2, "pass": 1, "fail": 0, "inconclusive": 1}
    assert result["attempts"][0]["observation"]["execution"] == "interrupted"
    assert verify(output) == result


def test_concurrent_access_is_refused(tmp_path):
    output = tmp_path / "run"
    with RunStore(output, create=True):
        with pytest.raises(ValueError, match="Another process"):
            RunStore(output)


def test_changed_target_cannot_resume(tmp_path):
    definition, target = inputs(tmp_path)
    output = tmp_path / "run"
    run(definition, target, output)
    target.write_text('def run(context):\n    return {"total": 0}\n')
    with pytest.raises(ValueError, match="same agent"):
        resume(output, target)


def test_tampered_report_fails_even_after_rehash(tmp_path):
    definition, target = inputs(tmp_path)
    output = tmp_path / "run"
    run(definition, target, output)
    report_path = output / "report.json"
    report = json.loads(report_path.read_text())
    report["verdict"] = "fail"
    report_path.write_text(json.dumps(report))
    integrity_path = output / "integrity.json"
    integrity = json.loads(integrity_path.read_text())
    integrity["files"]["report.json"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
    integrity_path.write_text(json.dumps(integrity))
    with pytest.raises(ValueError, match="reproduce"):
        verify(output)


def test_comparison_detects_regression_and_rejects_changed_definitions(tmp_path):
    definition, target = inputs(tmp_path)
    baseline, candidate = tmp_path / "before", tmp_path / "after"
    run(definition, target, baseline)
    target.write_text('def run(context):\n    return {"total": 0}\n')
    run(definition, target, candidate)
    result = compare(baseline, candidate, tmp_path / "comparison")
    assert result["verdict"] == "fail"
    assert result["changes"][0]["regression"]
    assert verify(tmp_path / "comparison") == result
    assert (tmp_path / "comparison" / "comparison.html").is_file()
    changed = task_spec()
    changed["checks"][0]["expected"] = 0
    definition.write_text(json.dumps(suite_spec(changed)))
    run(definition, target, tmp_path / "incompatible")
    with pytest.raises(ValueError, match="Incompatible"):
        compare(baseline, tmp_path / "incompatible", tmp_path / "invalid-comparison")
    assert not (tmp_path / "invalid-comparison").exists()


def test_required_manual_review_is_junit_error(tmp_path):
    definition, target = inputs(tmp_path)
    data = suite_spec()
    data["tasks"][0]["checks"].append(
        {"id": "review", "kind": "manual", "required": True, "reason": "Needs a human judgment"}
    )
    definition.write_text(json.dumps(data))
    output = tmp_path / "run"
    assert run(definition, target, output)["verdict"] == "inconclusive"
    root = ET.parse(output / "junit.xml").getroot()
    assert root.attrib["errors"] == "1"


def test_invalid_definition_does_not_create_run(tmp_path):
    definition, target = inputs(tmp_path)
    definition.write_text("{}")
    with pytest.raises(ValueError):
        run(definition, target, tmp_path / "run")
    assert not (tmp_path / "run").exists()


def test_cli_init_all_families_and_negative_control(tmp_path):
    def command(*args):
        return subprocess.run(
            [sys.executable, "-m", "eval_orchestrator.interfaces.agent_cli", *map(str, args)],
            capture_output=True,
            text=True,
            timeout=20,
        )

    project = tmp_path / "starter"
    assert command("init", project).returncode == 0
    assert command("validate", project / "starter.json").returncode == 0
    good = tmp_path / "good"
    result = command(
        "run",
        "--suite",
        project / "starter.json",
        "--agent",
        project / "reference_good.py",
        "--output",
        good,
    )
    assert result.returncode == 0, result.stderr
    report = verify(good)
    assert {a["family"] for a in report["attempts"]} == {"extraction", "grounded_qa", "workflow"}
    for name in ("broken", "refusal"):
        result = command(
            "run",
            "--suite",
            project / "starter.json",
            "--agent",
            project / f"reference_{name}.py",
            "--output",
            tmp_path / name,
        )
        assert result.returncode == 1, result.stderr


def test_atomic_write_failure_preserves_previous_file(tmp_path, monkeypatch):
    import os

    path = tmp_path / "record.json"
    path.write_bytes(b"old")

    def denied(*args):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(os, "replace", denied)
    with pytest.raises(OSError):
        atomic(path, b"new")
    assert path.read_bytes() == b"old"
    assert not list(tmp_path.glob("*.pending"))


def test_comparison_rescores_evidence_even_after_rehash(tmp_path):
    definition, target = inputs(tmp_path)
    run(definition, target, tmp_path / "before")
    run(definition, target, tmp_path / "after")
    output = tmp_path / "comparison"
    compare(tmp_path / "before", tmp_path / "after", output)
    path = output / "candidate-report.json"
    data = json.loads(path.read_text())
    data["attempts"][0]["observation"]["output"]["total"] = -1
    path.write_text(json.dumps(data))
    integrity = json.loads((output / "integrity.json").read_text())
    integrity["files"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (output / "integrity.json").write_text(json.dumps(integrity))
    with pytest.raises(ValueError, match="reproduce"):
        verify(output)


def test_consistency_summary_includes_interrupted_trials(tmp_path):
    definition, target = inputs(tmp_path)
    suite = parse_tasks(json.loads(definition.read_text()))
    output = tmp_path / "run"
    with RunStore(output, create=True) as store:
        store.initialize(suite.spec, manifest_for(suite, ProcessAgent(target), 2, 0))
        store.start(0)
    summary = resume(output, target)["task_summary"][0]
    assert summary["passed"] == 1
    assert summary["trials"] == 2
    assert summary["pass_fraction"] == 0.5
    assert summary["observed_duration_trials"] == 1
    result = verify(output)
    assert result["attempts"][0]["observation"]["duration_ms"] is None
    assert summary["mean_duration_ms"] == result["attempts"][1]["observation"]["duration_ms"]


@pytest.mark.parametrize("trial", [False, -1, "0"])
def test_invalid_trial_identity_is_rejected(tmp_path, trial):
    from eval_orchestrator.application.agent_eval import evaluate_attempt

    definition, target = inputs(tmp_path)
    suite = parse_tasks(json.loads(definition.read_text()))
    observation = ProcessAgent(target).execute(suite.tasks[0], 0, 0)
    with pytest.raises(ValueError):
        evaluate_attempt(suite.tasks[0], trial, observation)


def test_extreme_artifact_duration_is_a_validation_error(tmp_path):
    from eval_orchestrator.domain.observations import validate_observation

    definition, target = inputs(tmp_path)
    suite = parse_tasks(json.loads(definition.read_text()))
    observation = ProcessAgent(target).execute(suite.tasks[0], 0, 0)
    observation["duration_ms"] = 10**1000
    with pytest.raises(ValueError):
        validate_observation(suite.tasks[0], observation)


def test_resume_rejects_corrupt_started_marker_before_execution(tmp_path):
    definition, target = inputs(tmp_path)
    suite = parse_tasks(json.loads(definition.read_text()))
    output = tmp_path / "run"
    with RunStore(output, create=True) as store:
        store.initialize(suite.spec, manifest_for(suite, ProcessAgent(target), 1, 0))
        store.start(0)
    (output / "attempts/000000.started.json").write_text('{"slot": 12, "state": "started"}')
    with pytest.raises(ValueError, match="marker"):
        resume(output, target)
    assert not (output / "attempts/000000.json").exists()


def test_terminal_record_requires_its_started_marker(tmp_path):
    definition, target = inputs(tmp_path)
    output = tmp_path / "run"
    run(definition, target, output)
    (output / "attempts/000000.started.json").unlink()
    with RunStore(output) as store:
        with pytest.raises(ValueError, match="marker"):
            store.load(0)


@pytest.mark.parametrize("corruption", ["event", "state"])
def test_tool_evidence_must_replay(tmp_path, corruption):
    from test_agent_runner import task, workflow_spec

    from eval_orchestrator.domain.observations import validate_observation

    selected = task(workflow_spec())
    target = tmp_path / "agent.py"
    target.write_text(
        'def run(context):\n    context.call_tool("set_address", {"address": "New"})\n'
        '    return {"ok": True}\n'
    )
    observation = ProcessAgent(target).execute(selected, 0, 0)
    if corruption == "event":
        observation["events"][0]["effect"] = False
    else:
        observation["final_state"]["customer"]["address"] = "Forged"
    with pytest.raises(ValueError, match="reproduce|recorded tool effects"):
        validate_observation(selected, observation)
