"""Validate observations and replay local tool history without running an agent."""

import math
from typing import Any

from eval_orchestrator.domain.environment import Environment, same
from eval_orchestrator.domain.tasks import Task, integer, json_data, obj


def validate_observation(task: Task, value: object) -> dict[str, Any]:
    o = obj(
        value,
        {
            "execution",
            "output",
            "events",
            "final_state",
            "duration_ms",
            "tool_calls",
            "usage",
            "cost",
            "error",
            "stderr",
        },
        set(),
        "observation",
    )
    states = {
        "completed",
        "error",
        "timeout",
        "limit_exceeded",
        "cancelled",
        "interrupted",
        "not_started",
    }
    if not isinstance(o["execution"], str) or o["execution"] not in states:
        raise ValueError("Unknown execution state")
    duration = o["duration_ms"]
    if o["execution"] in {"interrupted", "not_started"}:
        if duration is not None:
            raise ValueError("Unobserved attempts must have unknown duration")
    elif (
        type(duration) not in {int, float}
        or not 0 <= duration <= 1e9
        or not math.isfinite(duration)
    ):
        raise ValueError("Invalid observed duration")
    if o["usage"] is not None or o["cost"] is not None:
        raise ValueError("Tokens/cost are not measured by this runner; they must remain null")
    if not isinstance(o["stderr"], str) or len(o["stderr"]) > 1048576:
        raise ValueError("Invalid worker stderr")
    if o["execution"] == "completed":
        if o["error"] is not None:
            raise ValueError("Completed execution cannot contain an error")
    elif not isinstance(o["error"], str) or not o["error"]:
        raise ValueError("Noncompleted execution needs a reason")
    json_data(o["output"])
    events = o["events"]
    if not isinstance(events, list) or len(events) > task.spec["limits"]["max_tool_calls"]:
        raise ValueError("Invalid observed tool count")
    integer(o["tool_calls"], "tool_calls", 0, 1000)
    if len(events) != o["tool_calls"]:
        raise ValueError("Tool count disagrees with evidence")
    environment = Environment(task.spec["environment"])
    for event in events:
        e = obj(
            event,
            {"index", "name", "arguments", "effect", "replayed", "policy_violation", "result"},
            set(),
            "tool event",
        )
        if not isinstance(e["name"], str) or not isinstance(e["arguments"], dict):
            raise ValueError("Invalid tool event arguments")
        environment.call(e["name"], e["arguments"])
        if not same(environment.events[-1], e):
            raise ValueError("Tool evidence does not reproduce")
    if not same(environment.state, o["final_state"]):
        raise ValueError("Final state disagrees with recorded tool effects")
    if o["execution"] in {"interrupted", "not_started"} and (events or o["output"] is not None):
        raise ValueError("Unobserved attempts cannot claim output or tool evidence")
    return o
