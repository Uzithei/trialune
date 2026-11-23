"""Versioned purchasing audit contracts. Money uses integer minor units."""

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum

MAX_INTEGER = 2**53 - 1
MAX_EVENTS = 10_000
MAX_CASES = 500
ENGINE_VERSION = "purchasing-v1.0"

EVENT_FIELDS: dict[str, dict[str, str]] = {
    "order_set": {"order_id": "text", "vendor": "text", "amount_minor": "positive"},
    "approval_granted": {
        "approval_id": "text",
        "order_id": "text",
        "order_version": "positive",
        "approver": "text",
        "expires_at": "integer",
    },
    "approval_revoked": {"approval_id": "text"},
    "purchase_requested": {
        "request_id": "text",
        "order_id": "text",
        "approval_id": "text",
        "idempotency_key": "text",
    },
    "purchase_committed": {
        "request_id": "text",
        "transaction_id": "text",
        "order_id": "text",
        "vendor": "text",
        "amount_minor": "positive",
        "idempotency_key": "text",
    },
    "request_failed": {"request_id": "text", "reason": "text"},
    "request_timeout": {"request_id": "text"},
    "finished": {"claimed_success": "boolean"},
}


def validate_scalar(value: object, kind: str, location: str) -> None:
    if kind == "text":
        valid = isinstance(value, str) and 0 < len(value) <= 256 and value == value.strip()
    elif kind == "boolean":
        valid = type(value) is bool
    else:
        valid = type(value) is int and (1 if kind == "positive" else 0) <= value <= MAX_INTEGER
    if not valid:
        raise ValueError(f"{location}: expected {kind} (bounded, no implicit coercion)")


def unique_text(values: tuple[str, ...], location: str, *, allow_empty: bool = False) -> None:
    if not isinstance(values, tuple) or (not values and not allow_empty):
        raise ValueError(f"{location}: expected {'possibly empty ' if allow_empty else ''}tuple")
    for value in values:
        validate_scalar(value, "text", location)
    if len(set(values)) != len(values):
        raise ValueError(f"{location}: duplicate identifiers")


def fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class Verdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class Policy:
    currency: str
    budget_minor: int
    max_purchase_minor: int
    approvers: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.currency) != 3 or not self.currency.isascii() or not self.currency.isupper():
            raise ValueError("currency: expected three uppercase ASCII letters")
        if not self.currency.isalpha():
            raise ValueError("currency: expected letters")
        validate_scalar(self.budget_minor, "positive", "budget_minor")
        validate_scalar(self.max_purchase_minor, "positive", "max_purchase_minor")
        unique_text(self.approvers, "approvers")


@dataclass(frozen=True)
class Event:
    event_id: str
    at: int
    kind: str
    fields: tuple[tuple[str, str | int | bool], ...]

    def __post_init__(self) -> None:
        validate_scalar(self.event_id, "text", "event_id")
        validate_scalar(self.at, "integer", "at")
        if self.kind not in EVENT_FIELDS:
            raise ValueError(f"Unknown event kind: {self.kind}")
        if not isinstance(self.fields, tuple) or any(not isinstance(p, tuple) for p in self.fields):
            raise ValueError("Event fields must be immutable pairs")
        data = dict(self.fields)
        if len(data) != len(self.fields) or set(data) != set(EVENT_FIELDS[self.kind]):
            raise ValueError(f"{self.kind}: incorrect or duplicate fields")
        for name, kind in EVENT_FIELDS[self.kind].items():
            validate_scalar(data[name], kind, f"{self.kind}.{name}")

    def text(self, key: str) -> str:
        value = dict(self.fields)[key]
        if not isinstance(value, str):
            raise ValueError(f"{key} is not text")
        return value

    def number(self, key: str) -> int:
        value = dict(self.fields)[key]
        if type(value) is not int:
            raise ValueError(f"{key} is not an integer")
        return value

    def to_dict(self) -> dict[str, object]:
        return {"event_id": self.event_id, "at": self.at, "kind": self.kind, **dict(self.fields)}


@dataclass(frozen=True)
class Case:
    case_id: str
    scenario_version: str
    required: bool
    expected_orders: tuple[str, ...]
    events: tuple[Event, ...]

    def __post_init__(self) -> None:
        validate_scalar(self.case_id, "text", "case_id")
        validate_scalar(self.scenario_version, "text", "scenario_version")
        validate_scalar(self.required, "boolean", "required")
        unique_text(self.expected_orders, "expected_orders", allow_empty=True)
        if not isinstance(self.events, tuple) or not 1 <= len(self.events) <= MAX_EVENTS:
            raise ValueError(f"events: expected 1..{MAX_EVENTS} immutable events")
        ids = tuple(event.event_id for event in self.events)
        unique_text(ids, "event IDs")
        if any(a.at > b.at for a, b in zip(self.events, self.events[1:], strict=False)):
            raise ValueError("Events must be ordered by nondecreasing at; array order breaks ties")

    def contract(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "scenario_version": self.scenario_version,
            "required": self.required,
            "expected_orders": sorted(self.expected_orders),
        }


@dataclass(frozen=True)
class Suite:
    suite_id: str
    policy: Policy
    cases: tuple[Case, ...]

    def __post_init__(self) -> None:
        validate_scalar(self.suite_id, "text", "suite_id")
        if not isinstance(self.cases, tuple) or not 1 <= len(self.cases) <= MAX_CASES:
            raise ValueError(f"cases: expected 1..{MAX_CASES} immutable cases")
        unique_text(tuple(case.case_id for case in self.cases), "case IDs")
        if not any(case.required for case in self.cases):
            raise ValueError("At least one required case is necessary for a release verdict")

    @property
    def contract_sha256(self) -> str:
        return fingerprint(
            {
                "suite_id": self.suite_id,
                "policy": asdict(self.policy),
                "cases": [c.contract() for c in sorted(self.cases, key=lambda c: c.case_id)],
            }
        )


@dataclass(frozen=True)
class Finding:
    code: str
    category: str
    message: str
    event_ids: tuple[str, ...]


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    required: bool
    verdict: Verdict
    findings: tuple[Finding, ...]
    spent_minor: int
    committed_orders: tuple[str, ...]
    pending_requests: tuple[str, ...]
