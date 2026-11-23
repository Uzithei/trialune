"""Resettable JSON-state tools. The runner owns state and records authoritative effects."""

import json
from typing import Any

from eval_orchestrator.domain.tasks import canonical, json_data


def segments(pointer: str) -> list[str]:
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer.split("/")[1:]]


def lookup(value: Any, pointer: str) -> Any:
    for key in segments(pointer):
        if isinstance(value, dict):
            value = value[key]
        elif isinstance(value, list) and key.isdigit() and (key == "0" or not key.startswith("0")):
            value = value[int(key)]
        else:
            raise KeyError(pointer)
    return value


def same(left: object, right: object) -> bool:
    return canonical(left) == canonical(right)


def valid_arguments(arguments: dict[str, Any], parameters: dict[str, Any]) -> bool:
    properties = parameters["properties"]
    if arguments.keys() - properties.keys() or not set(parameters["required"]) <= arguments.keys():
        return False
    for name, value in arguments.items():
        kind = properties[name]["type"]
        matches = {
            "string": isinstance(value, str),
            "integer": type(value) is int,
            "number": type(value) in {int, float},
            "boolean": type(value) is bool,
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "null": value is None,
        }[kind]
        if not matches:
            return False
        if "enum" in properties[name] and not any(same(value, v) for v in properties[name]["enum"]):
            return False
    return True


class Environment:
    def __init__(self, specification: dict[str, Any]) -> None:
        self.state = json.loads(canonical(specification["state"]))
        self.tools = {tool["name"]: tool for tool in specification["tools"]}
        self.events: list[dict[str, Any]] = []
        self.counts: dict[str, int] = {}
        self.cache: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}

    def descriptions(self) -> list[dict[str, Any]]:
        # Neither initial hidden state, permission decisions nor faults go to the agent.
        return [
            {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}
            for t in self.tools.values()
        ]

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        json_data(arguments)
        record: dict[str, Any] = {
            "index": len(self.events) + 1,
            "name": name,
            "arguments": json.loads(canonical(arguments)),
            "effect": False,
            "replayed": False,
            "policy_violation": False,
        }
        tool = self.tools.get(name)
        if tool is None or not tool.get("allowed", True):
            result = {"ok": False, "error": "tool_not_allowed"}
            record["policy_violation"] = True
        elif not valid_arguments(arguments, tool["parameters"]):
            result = {"ok": False, "error": "invalid_arguments"}
            record["policy_violation"] = True
        else:
            result = self._execute(tool, arguments, record)
        record["result"] = json.loads(canonical(result))
        self.events.append(record)
        return result

    def _execute(
        self, tool: dict[str, Any], arguments: dict[str, Any], record: dict[str, Any]
    ) -> dict[str, Any]:
        name = tool["name"]
        self.counts[name] = self.counts.get(name, 0) + 1
        cache_key = None
        signature = canonical(arguments)
        if "idempotency_argument" in tool:
            value = arguments.get(tool["idempotency_argument"])
            if not isinstance(value, str) or not value:
                record["policy_violation"] = True
                return {"ok": False, "error": "missing_idempotency_key"}
            cache_key = (name, value)
            if cache_key in self.cache:
                original, previous = self.cache[cache_key]
                if original != signature:
                    record["policy_violation"] = True
                    return {"ok": False, "error": "idempotency_conflict"}
                record["replayed"] = True
                return json.loads(canonical(previous))  # type: ignore[no-any-return]
        fault = next(
            (f["mode"] for f in tool.get("faults", []) if f["call"] == self.counts[name]), None
        )
        if fault == "error":
            return {"ok": False, "error": "injected_failure"}
        path = []
        for part in segments(tool["path"]):
            if part.startswith("{") and part.endswith("}"):
                parameter = arguments.get(part[1:-1])
                if not isinstance(parameter, str) or not parameter:
                    return {"ok": False, "error": "invalid_path_argument"}
                path.append(parameter)
            else:
                path.append(part)
        pointer = "".join("/" + p.replace("~", "~0").replace("/", "~1") for p in path)
        try:
            if tool["operation"] == "read":
                value = lookup(self.state, pointer)
            else:
                if not path or tool["value_argument"] not in arguments:
                    return {"ok": False, "error": "missing_value_or_path"}
                parent_pointer = "".join(
                    "/" + p.replace("~", "~0").replace("/", "~1") for p in path[:-1]
                )
                parent = lookup(self.state, parent_pointer)
                if not isinstance(parent, dict) or path[-1] not in parent:
                    return {"ok": False, "error": "path_not_found"}
                value = json.loads(canonical(arguments[tool["value_argument"]]))
                if tool["operation"] == "set":
                    parent[path[-1]] = value
                else:
                    if not isinstance(parent[path[-1]], list):
                        return {"ok": False, "error": "append_target_not_array"}
                    parent[path[-1]].append(value)
                    value = parent[path[-1]]
                record["effect"] = True
            result = {"ok": True, "value": json.loads(canonical(value))}
            if cache_key:
                self.cache[cache_key] = (signature, result)
            if fault == "timeout_after_effect":
                return {"ok": False, "error": "timeout_outcome_unknown"}
            return result
        except (KeyError, IndexError):
            return {"ok": False, "error": "path_not_found"}
