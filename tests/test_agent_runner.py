import copy
import json
import time

import pytest

from eval_orchestrator.adapters.process_agent import ProcessAgent
from eval_orchestrator.application.agent_eval import run_attempt
from eval_orchestrator.domain.environment import Environment
from eval_orchestrator.domain.tasks import parse_tasks


def task_spec():
    return {
        "id": "extract",
        "version": "1",
        "family": "extraction",
        "required": True,
        "input": {"prompt": "Return the invoice total of 42", "documents": []},
        "environment": {"state": {}, "tools": []},
        "checks": [
            {"id": "total", "kind": "equals", "required": True, "pointer": "/total", "expected": 42}
        ],
        "limits": {"timeout_seconds": 3, "max_tool_calls": 5},
    }


def suite_spec(task=None):
    return {"schema_version": 1, "name": "test", "version": "1", "tasks": [task or task_spec()]}


def task(value=None):
    return parse_tasks(suite_spec(value)).tasks[0]


def agent(tmp_path, source):
    path = tmp_path / "custom_agent.py"
    path.write_text(source)
    return ProcessAgent(path)


def workflow_spec():
    spec = task_spec()
    spec.update(id="update", family="workflow")
    spec["environment"] = {
        "state": {"customer": {"address": "Old"}},
        "tools": [
            {
                "name": "set_address",
                "description": "Update the customer address",
                "parameters": {
                    "properties": {"address": {"type": "string"}},
                    "required": ["address"],
                },
                "operation": "set",
                "path": "/customer/address",
                "value_argument": "address",
            }
        ],
    }
    spec["checks"] = [
        {
            "id": "state",
            "kind": "state_equals",
            "required": True,
            "pointer": "/customer/address",
            "expected": "New",
        },
        {"id": "policy", "kind": "tool_policy", "required": True},
    ]
    return spec


def test_external_agent_runs_and_output_is_actually_graded(tmp_path):
    good = agent(tmp_path, 'def run(context):\n    return {"total": 42}\n')
    result = run_attempt(task(), 0, 1, good)
    assert result["verdict"] == "pass"
    assert result["observation"]["execution"] == "completed"
    bad = agent(tmp_path, 'def run(context):\n    return {"total": 0}\n')
    assert run_attempt(task(), 0, 1, bad)["verdict"] == "fail"


def test_agent_gets_inputs_but_not_expected_answers_or_hidden_state(tmp_path):
    runner = agent(
        tmp_path,
        """def run(context):
    assert not hasattr(context, "checks")
    assert not hasattr(context, "environment")
    assert not hasattr(context, "expected")
    return {"total": int(context.prompt.split()[-1])}
""",
    )
    assert run_attempt(task(), 0, 1, runner)["verdict"] == "pass"


def test_tools_change_parent_state_and_generate_authoritative_events(tmp_path):
    runner = agent(
        tmp_path,
        """def run(context):
    result = context.call_tool("set_address", {"address": "New"})
    return {"updated": result["ok"]}
""",
    )
    result = run_attempt(task(workflow_spec()), 0, 1, runner)
    assert result["verdict"] == "pass"
    assert result["observation"]["final_state"]["customer"]["address"] == "New"
    assert result["observation"]["events"][0]["effect"] is True


def test_prose_claim_does_not_change_state(tmp_path):
    runner = agent(tmp_path, 'def run(context):\n    return {"updated": True}\n')
    assert run_attempt(task(workflow_spec()), 0, 1, runner)["verdict"] == "fail"


def test_forbidden_action_remains_failure_even_if_agent_finishes(tmp_path):
    spec = workflow_spec()
    spec["environment"]["tools"][0]["allowed"] = False
    spec["checks"][0]["expected"] = "Old"
    runner = agent(
        tmp_path,
        """def run(context):
    context.call_tool("set_address", {"address": "New"})
    return "done"
""",
    )
    result = run_attempt(task(spec), 0, 1, runner)
    assert result["verdict"] == "fail"
    assert result["observation"]["final_state"]["customer"]["address"] == "Old"


def test_fresh_process_and_environment_for_every_trial(tmp_path):
    runner = agent(
        tmp_path,
        """counter = 0
def run(context):
    global counter
    counter += 1
    context.call_tool("set_address", {"address": "New"})
    assert counter == 1
    return {}
""",
    )
    selected = task(workflow_spec())
    for trial in range(3):
        result = run_attempt(selected, trial, 7, runner)
        assert result["verdict"] == "pass"
        assert len(result["observation"]["events"]) == 1
    assert selected.spec["environment"]["state"]["customer"]["address"] == "Old"


def test_worker_exception_is_not_a_scoring_failure_or_pass(tmp_path):
    runner = agent(tmp_path, 'def run(context):\n    raise RuntimeError("example crash")\n')
    result = run_attempt(task(), 0, 1, runner)
    assert result["verdict"] == "inconclusive"
    assert result["observation"]["execution"] == "error"
    assert "example crash" in result["observation"]["stderr"]


def test_hung_worker_is_terminated_within_deadline(tmp_path):
    spec = task_spec()
    spec["limits"]["timeout_seconds"] = 0.2
    runner = agent(tmp_path, "import time\ndef run(context):\n    time.sleep(30)\n")
    start = time.monotonic()
    result = run_attempt(task(spec), 0, 1, runner)
    assert time.monotonic() - start < 3
    assert result["observation"]["execution"] == "timeout"
    assert result["verdict"] == "inconclusive"


def test_tool_call_budget_stops_execution(tmp_path):
    spec = workflow_spec()
    spec["limits"]["max_tool_calls"] = 1
    runner = agent(
        tmp_path,
        """def run(context):
    context.call_tool("set_address", {"address": "New"})
    context.call_tool("set_address", {"address": "New"})
    return {}
""",
    )
    result = run_attempt(task(spec), 0, 1, runner)
    assert result["observation"]["execution"] == "limit_exceeded"
    assert result["verdict"] == "inconclusive"
    assert len(result["observation"]["events"]) == 1


@pytest.mark.parametrize(
    "source",
    [
        'def run(context):\n    print("x" * 2000000)\n    return {}\n',
        'def run(context):\n    return ["x" * 80000] * 4\n',
    ],
)
def test_unbounded_logs_or_output_are_stopped(tmp_path, source):
    result = run_attempt(task(), 0, 1, agent(tmp_path, source))
    assert result["observation"]["execution"] == "limit_exceeded"


def test_malformed_protocol_is_visible(tmp_path):
    runner = agent(
        tmp_path, 'import os\ndef run(context):\n    os.write(1, b"invalid\\n")\n    return {}\n'
    )
    assert run_attempt(task(), 0, 1, runner)["observation"]["execution"] == "error"


def test_default_environment_does_not_forward_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_AGENT_SECRET", "not-a-real-secret")
    path = tmp_path / "custom_agent.py"
    path.write_text(
        "import os\ndef run(context):\n"
        '    return {"total": 42 if "TEST_AGENT_SECRET" not in os.environ else 0}\n'
    )
    assert run_attempt(task(), 0, 1, ProcessAgent(path))["verdict"] == "pass"
    forwarded = ProcessAgent(path, ("TEST_AGENT_SECRET",))
    assert run_attempt(task(), 0, 1, forwarded)["verdict"] == "fail"
    assert "not-a-real-secret" not in json.dumps(forwarded.identity)


def test_manual_required_check_cannot_pass(tmp_path):
    spec = task_spec()
    spec["checks"].append(
        {
            "id": "review",
            "kind": "manual",
            "required": True,
            "reason": "Semantic support needs review",
        }
    )
    result = run_attempt(
        task(spec), 0, 1, agent(tmp_path, 'def run(context):\n    return {"total": 42}\n')
    )
    assert result["verdict"] == "inconclusive"


def test_task_is_immutable_even_when_caller_changes_copy():
    original = task()
    changed = original.spec
    changed["checks"][0]["expected"] = 0
    assert original.spec["checks"][0]["expected"] == 42


def test_idempotent_recovery_after_ambiguous_effect():
    tool = workflow_spec()["environment"]["tools"][0]
    tool.update(idempotency_argument="key", faults=[{"call": 1, "mode": "timeout_after_effect"}])
    tool["parameters"]["properties"]["key"] = {"type": "string"}
    tool["parameters"]["required"].append("key")
    env = Environment({"state": {"customer": {"address": "Old"}}, "tools": [tool]})
    arguments = {"address": "New", "key": "one"}
    assert env.call("set_address", arguments)["error"] == "timeout_outcome_unknown"
    assert env.call("set_address", arguments)["ok"] is True
    assert sum(e["effect"] for e in env.events) == 1
    assert env.events[-1]["replayed"] is True
    assert (
        env.call("set_address", {**arguments, "address": "Other"})["error"]
        == "idempotency_conflict"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(schema_version=True),
        lambda d: d["tasks"][0].update(required=False),
        lambda d: d["tasks"][0]["limits"].update(timeout_seconds=False),
        lambda d: d["tasks"][0]["checks"][0].update(kind="arbitrary_python"),
        lambda d: d["tasks"][0]["checks"][0].update(required="yes"),
        lambda d: d["tasks"][0]["input"].update(secret="not accepted"),
    ],
)
def test_invalid_definitions_fail_before_execution(mutation):
    definition = copy.deepcopy(suite_spec())
    mutation(definition)
    with pytest.raises(ValueError):
        parse_tasks(definition)
