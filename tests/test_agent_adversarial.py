import json
import signal
import subprocess
import sys
import time

import pytest
from test_agent_runner import agent, run_attempt, suite_spec, task, task_spec, workflow_spec

from eval_orchestrator.domain.tasks import parse_tasks
from eval_orchestrator.interfaces.agent_cli import resume, verify


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["tasks"][0].update(family=[]),
        lambda d: d["tasks"][0]["checks"][0].update(kind={}),
        lambda d: d["tasks"][0]["environment"]["tools"][0].update(operation=[]),
        lambda d: d["tasks"][0]["environment"]["tools"][0].update(faults=[{"call": 1, "mode": []}]),
        lambda d: d["tasks"][0]["environment"]["tools"][0]["parameters"]["properties"][
            "address"
        ].update(type=[]),
        lambda d: d["tasks"][0]["limits"].update(max_tool_calls=10**1000),
    ],
)
def test_adversarial_definitions_raise_validation_errors(mutation):
    definition = suite_spec(workflow_spec())
    mutation(definition)
    with pytest.raises(ValueError):
        parse_tasks(definition)


def test_worker_descendants_are_terminated(tmp_path):
    marker = tmp_path / "descendant-survived"
    child = (
        "import time; from pathlib import Path; time.sleep(0.8); "
        f"Path({str(marker)!r}).write_text('bad')"
    )
    source = (
        "import subprocess, sys, time\ndef run(context):\n"
        f"    subprocess.Popen([sys.executable, '-c', {child!r}])\n"
        "    time.sleep(30)\n"
    )
    spec = task_spec()
    spec["limits"]["timeout_seconds"] = 0.25
    result = run_attempt(task(spec), 0, 0, agent(tmp_path, source))
    assert result["observation"]["execution"] == "timeout"
    time.sleep(0.85)
    assert not marker.exists()


def test_valid_final_state_does_not_erase_forbidden_history(tmp_path):
    source = """def run(context):
    context.call_tool("forbidden", {})
    context.call_tool("set_address", {"address": "New"})
    return {}
"""
    result = run_attempt(task(workflow_spec()), 0, 0, agent(tmp_path, source))
    assert result["checks"][0]["status"] == "pass"
    assert result["checks"][1]["status"] == "fail"
    assert result["verdict"] == "fail"


def test_output_json_boolean_is_not_equal_to_integer(tmp_path):
    spec = task_spec()
    spec["checks"][0]["expected"] = 1
    runner = agent(tmp_path, 'def run(context):\n    return {"total": True}\n')
    assert run_attempt(task(spec), 0, 0, runner)["verdict"] == "fail"


def test_cancellation_is_saved_and_resume_does_not_retry_it(tmp_path):
    definition = tmp_path / "tasks.json"
    definition.write_text(json.dumps(suite_spec()))
    target = tmp_path / "slow.py"
    ready = tmp_path / "ready"
    target.write_text(
        "import time\nfrom pathlib import Path\ndef run(context):\n"
        f"    Path({str(ready)!r}).write_text('ready')\n    time.sleep(30)\n"
    )
    output = tmp_path / "run"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "eval_orchestrator.interfaces.agent_cli",
            "run",
            "--suite",
            str(definition),
            "--agent",
            str(target),
            "--output",
            str(output),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        process.send_signal(signal.SIGINT)
        process.communicate(timeout=3)
        assert process.returncode == 130
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    before = (output / "attempts/000000.json").read_bytes()
    result = resume(output, target)
    assert result["verdict"] == "inconclusive"
    assert result["attempts"][0]["observation"]["execution"] == "cancelled"
    assert (output / "attempts/000000.json").read_bytes() == before
    assert verify(output) == result
