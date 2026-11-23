"""Strict, data-only evaluation contracts. Nested configuration is stored immutably."""

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any

ENGINE = "agent-eval-1"
FAMILIES = {"extraction", "grounded_qa", "workflow"}
CHECKS = {
    "equals",
    "text_match",
    "answer_set",
    "citations",
    "state_equals",
    "tool_policy",
    "manual",
}


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def obj(value: object, required: set[str], optional: set[str], where: str) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or not required <= value.keys()
        or value.keys() - required - optional
    ):
        raise ValueError(f"{where}: expected {sorted(required)}, optional {sorted(optional)}")
    return value


def text(value: object, where: str, maximum: int = 100_000) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{where}: expected nonempty text up to {maximum} characters")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{where}: invalid Unicode") from exc
    return value


def identifier(value: object, where: str) -> str:
    result = text(value, where, 100)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", result):
        raise ValueError(f"{where}: use letters, digits, dot, underscore or hyphen")
    return result


def integer(value: object, where: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{where}: expected integer {low}..{high}")
    return value


def boolean(value: object, where: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{where}: expected boolean")
    return value


def items(value: object, where: str, maximum: int, *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list) or not (1 if nonempty else 0) <= len(value) <= maximum:
        raise ValueError(f"{where}: expected bounded array (max {maximum})")
    return value


def pointer(value: object) -> str:
    if not isinstance(value, str) or (value and not value.startswith("/")) or len(value) > 500:
        raise ValueError("Expected JSON pointer, empty or starting with /")
    if re.search(r"~(?![01])", value):
        raise ValueError("Invalid JSON pointer escape")
    return value


def json_data(value: object, depth: int = 0) -> None:
    if depth > 32:
        raise ValueError("JSON nesting exceeds 32 levels")
    if value is None or type(value) is bool:
        return
    if type(value) in {int, float}:
        assert isinstance(value, (int, float))
        if abs(value) > 2**53 - 1 or not math.isfinite(value):
            raise ValueError("Numbers must be finite and within the safe integer range")
    elif isinstance(value, str):
        if len(value) > 100_000:
            raise ValueError("Text value too long")
        value.encode("utf-8")
    elif isinstance(value, list):
        if len(value) > 10_000:
            raise ValueError("Array too large")
        for entry in value:
            json_data(entry, depth + 1)
    elif isinstance(value, dict):
        if len(value) > 10_000 or any(not isinstance(key, str) for key in value):
            raise ValueError("Invalid JSON object")
        for key, entry in value.items():
            json_data(key, depth + 1)
            json_data(entry, depth + 1)
    else:
        raise ValueError("Value is not JSON data")


def validate_tool(tool: object) -> None:
    t = obj(
        tool,
        {"name", "description", "parameters", "operation", "path"},
        {"value_argument", "allowed", "idempotency_argument", "faults"},
        "tool",
    )
    identifier(t["name"], "tool name")
    text(t["description"], "tool description", 2000)
    if not isinstance(t["operation"], str) or t["operation"] not in {"read", "set", "append"}:
        raise ValueError("Unknown tool operation")
    pointer(t["path"])
    boolean(t.get("allowed", True), "tool allowed")
    params = obj(t["parameters"], {"properties", "required"}, set(), "parameters")
    if not isinstance(params["properties"], dict) or len(params["properties"]) > 30:
        raise ValueError("Tool properties must be a bounded object")
    for name, schema in params["properties"].items():
        identifier(name, "parameter name")
        s = obj(schema, {"type"}, {"enum"}, "parameter")
        if not isinstance(s["type"], str) or s["type"] not in {
            "string",
            "integer",
            "number",
            "boolean",
            "object",
            "array",
            "null",
        }:
            raise ValueError("Unknown parameter type")
        if "enum" in s:
            items(s["enum"], "enum", 100, nonempty=True)
    required = items(params["required"], "required parameters", 30)
    if any(not isinstance(key, str) or key not in params["properties"] for key in required):
        raise ValueError("Unknown required parameter")
    if len(set(required)) != len(required):
        raise ValueError("Duplicate required parameter")
    for part in t["path"].split("/")[1:]:
        if "{" in part or "}" in part:
            if (
                not re.fullmatch(r"\{[A-Za-z0-9_.-]+\}", part)
                or part[1:-1] not in params["properties"]
            ):
                raise ValueError("Path templates must name whole declared parameter segments")
    if t["operation"] != "read" and "value_argument" not in t:
        raise ValueError("Mutating tool requires value_argument")
    for key in ("value_argument", "idempotency_argument"):
        if key in t and (not isinstance(t[key], str) or t[key] not in params["properties"]):
            raise ValueError(f"{key} must name a declared parameter")
    seen = set()
    for fault in items(t.get("faults", []), "faults", 20):
        f = obj(fault, {"call", "mode"}, set(), "fault")
        number = integer(f["call"], "fault call", 1, 1000)
        if (
            number in seen
            or not isinstance(f["mode"], str)
            or f["mode"] not in {"error", "timeout_after_effect"}
        ):
            raise ValueError("Invalid or duplicate fault")
        seen.add(number)


def validate_check(check: object) -> None:
    c = obj(
        check,
        {"id", "kind", "required"},
        {"pointer", "expected", "casefold", "allowed", "reason"},
        "check",
    )
    identifier(c["id"], "check ID")
    boolean(c["required"], "check required")
    if not isinstance(c["kind"], str) or c["kind"] not in CHECKS:
        raise ValueError("Unknown check kind")
    allowed = {"id", "kind", "required"}
    if c["kind"] in {"equals", "state_equals", "text_match", "answer_set"}:
        allowed |= {"pointer", "expected"}
        if not {"pointer", "expected"} <= c.keys():
            raise ValueError("Value check requires pointer and expected")
        pointer(c["pointer"])
    if c["kind"] in {"text_match", "answer_set"}:
        allowed.add("casefold")
        boolean(c.get("casefold", False), "casefold")
        values = c["expected"] if c["kind"] == "answer_set" else [c["expected"]]
        for value in items(values, "expected answers", 100, nonempty=True):
            text(value, "expected text")
    if c["kind"] == "citations":
        allowed |= {"pointer", "allowed"}
        if not {"pointer", "allowed"} <= c.keys():
            raise ValueError("Citation check requires pointer and allowed IDs")
        pointer(c["pointer"])
        for value in items(c["allowed"], "allowed citations", 100):
            identifier(value, "document ID")
    if c["kind"] == "manual":
        allowed.add("reason")
        text(c.get("reason"), "manual check reason")
    if c.keys() - allowed:
        raise ValueError("Fields do not apply to this evaluator")


@dataclass(frozen=True)
class Task:
    frozen_json: str

    @property
    def spec(self) -> dict[str, Any]:
        return json.loads(self.frozen_json)  # type: ignore[no-any-return]

    @property
    def task_id(self) -> str:
        return str(self.spec["id"])


@dataclass(frozen=True)
class TaskSuite:
    frozen_json: str
    tasks: tuple[Task, ...]

    @property
    def spec(self) -> dict[str, Any]:
        return json.loads(self.frozen_json)  # type: ignore[no-any-return]

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.frozen_json.encode()).hexdigest()


def parse_tasks(data: object) -> TaskSuite:
    json_data(data)
    root = obj(data, {"schema_version", "name", "version", "tasks"}, set(), "suite")
    integer(root["schema_version"], "schema_version", 1, 1)
    identifier(root["name"], "suite name")
    identifier(root["version"], "suite version")
    tasks = []
    task_ids = set()
    for entry in items(root["tasks"], "tasks", 500, nonempty=True):
        t = obj(
            entry,
            {"id", "version", "family", "required", "input", "environment", "checks", "limits"},
            set(),
            "task",
        )
        task_id = identifier(t["id"], "task ID")
        if task_id in task_ids:
            raise ValueError("Duplicate task ID")
        task_ids.add(task_id)
        identifier(t["version"], "task version")
        if not isinstance(t["family"], str) or t["family"] not in FAMILIES:
            raise ValueError("Unsupported task family")
        boolean(t["required"], "task required")
        inp = obj(t["input"], {"prompt", "documents"}, set(), "input")
        text(inp["prompt"], "prompt")
        docs = set()
        for document in items(inp["documents"], "documents", 100):
            d = obj(document, {"id", "text"}, set(), "document")
            doc_id = identifier(d["id"], "document ID")
            if doc_id in docs:
                raise ValueError("Duplicate document ID")
            docs.add(doc_id)
            text(d["text"], "document text")
        env = obj(t["environment"], {"state", "tools"}, set(), "environment")
        if not isinstance(env["state"], dict):
            raise ValueError("Environment state must be an object")
        tools = set()
        for tool in items(env["tools"], "tools", 50):
            validate_tool(tool)
            if tool["name"] in tools:
                raise ValueError("Duplicate tool name")
            tools.add(tool["name"])
        check_ids = set()
        required = False
        for check in items(t["checks"], "checks", 100, nonempty=True):
            validate_check(check)
            if check["id"] in check_ids:
                raise ValueError("Duplicate check ID")
            check_ids.add(check["id"])
            required |= check["required"]
            if check["kind"] == "citations" and not set(check["allowed"]) <= docs:
                raise ValueError("Citation check refers to missing input documents")
        if not required:
            raise ValueError("Every task needs a required check")
        limits = obj(t["limits"], {"timeout_seconds", "max_tool_calls"}, set(), "limits")
        timeout = limits["timeout_seconds"]
        if type(timeout) not in {int, float} or not 0.05 <= timeout <= 300:
            raise ValueError("timeout_seconds must be 0.05..300")
        integer(limits["max_tool_calls"], "max_tool_calls", 0, 1000)
        tasks.append(Task(canonical(t)))
    if not any(t.spec["required"] for t in tasks):
        raise ValueError("Suite needs at least one required task")
    return TaskSuite(canonical(root), tuple(tasks))
