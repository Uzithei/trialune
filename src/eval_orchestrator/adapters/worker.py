"""Python agent SDK and worker. Trusted user code runs in a dedicated OS process."""

import contextlib
import json
import runpy
import sys
from dataclasses import dataclass, field
from typing import Any, TextIO

from eval_orchestrator.adapters.trace_json import strict_json
from eval_orchestrator.domain.tasks import canonical, json_data


@dataclass
class AgentContext:
    task_id: str
    prompt: str
    documents: list[dict[str, str]]
    tools: list[dict[str, Any]]
    trial: int
    seed: int
    _input: TextIO = field(repr=False)
    _output: TextIO = field(repr=False)
    _next_id: int = field(default=0, repr=False)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        message = {"type": "tool_call", "id": self._next_id, "name": name, "arguments": arguments}
        self._output.write(canonical(message) + "\n")
        self._output.flush()
        line = self._input.readline(262145)
        response = strict_json(line.encode())
        if not isinstance(response, dict) or response.get("id") != self._next_id:
            raise ValueError("Invalid tool response from runner")
        result = response["result"]
        if not isinstance(result, dict):
            raise ValueError("Tool response is not an object")
        return result


def main() -> int:
    protocol_out = sys.stdout
    initial = strict_json(sys.stdin.buffer.readline(8 * 1024 * 1024 + 1))
    if not isinstance(initial, dict):
        raise ValueError("Missing worker configuration")
    context = AgentContext(
        initial["task_id"],
        initial["prompt"],
        initial["documents"],
        initial["tools"],
        initial["trial"],
        initial["seed"],
        sys.stdin,
        protocol_out,
    )
    # Capture ordinary print() logs on stderr, away from the structured protocol.
    with contextlib.redirect_stdout(sys.stderr):
        sys.path.insert(0, initial["import_directory"])
        module = runpy.run_path(initial["agent_file"], run_name="agent_under_test")
        function = module.get("run")
        if not callable(function):
            raise ValueError("Agent file must define run(context)")
        output = function(context)
        json_data(output)
    protocol_out.write(json.dumps({"type": "final", "output": output}, allow_nan=False) + "\n")
    protocol_out.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
