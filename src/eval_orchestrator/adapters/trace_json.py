"""Strict local JSON boundary; duplicate keys, unknown fields and huge inputs fail."""

import json
from pathlib import Path
from typing import Any

from eval_orchestrator.domain.purchasing import EVENT_FIELDS, Case, Event, Policy, Suite

MAX_BYTES = 8 * 1024 * 1024


def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ValueError(f"Nonfinite JSON number: {value}")


def strict_json(raw: bytes) -> object:
    if len(raw) > MAX_BYTES:
        raise ValueError(f"Input exceeds {MAX_BYTES} bytes")
    try:
        return json.loads(
            raw.decode("utf-8"), object_pairs_hook=object_pairs, parse_constant=reject_constant
        )
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("Input must be bounded UTF-8 JSON") from exc


def fields(value: object, expected: set[str], location: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{location}: expected exactly {', '.join(sorted(expected))}")
    return value


def array(value: object, location: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{location}: expected array")
    return value


def parse_suite(raw: bytes) -> Suite:
    root = fields(strict_json(raw), {"schema_version", "suite_id", "policy", "cases"}, "suite")
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise ValueError("Only schema_version 1 is supported")
    p = fields(
        root["policy"], {"currency", "budget_minor", "max_purchase_minor", "approvers"}, "policy"
    )
    if not isinstance(p["currency"], str):
        raise ValueError("currency must be text")
    policy = Policy(
        p["currency"],
        p["budget_minor"],
        p["max_purchase_minor"],
        tuple(array(p["approvers"], "approvers")),
    )
    cases = []
    for item in array(root["cases"], "cases"):
        c = fields(
            item, {"case_id", "scenario_version", "required", "expected_orders", "events"}, "case"
        )
        events = []
        for event in array(c["events"], "events"):
            if not isinstance(event, dict) or not isinstance(event.get("kind"), str):
                raise ValueError("Event requires a text kind")
            kind = event["kind"]
            if kind not in EVENT_FIELDS:
                raise ValueError(f"Unsupported event kind: {kind}")
            e = fields(event, {"event_id", "at", "kind"} | set(EVENT_FIELDS[kind]), "event")
            events.append(
                Event(
                    e["event_id"], e["at"], kind, tuple((key, e[key]) for key in EVENT_FIELDS[kind])
                )
            )
        cases.append(
            Case(
                c["case_id"],
                c["scenario_version"],
                c["required"],
                tuple(array(c["expected_orders"], "expected_orders")),
                tuple(events),
            )
        )
    return Suite(root["suite_id"], policy, tuple(cases))


def read_input(path: Path) -> bytes:
    with path.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError(f"Input exceeds {MAX_BYTES} bytes")
    return raw
