"""Release decisions from observed purchasing traces; no model or account access."""

from dataclasses import asdict, dataclass

from eval_orchestrator.domain.purchasing import (
    ENGINE_VERSION,
    CaseResult,
    Policy,
    Suite,
    Verdict,
    fingerprint,
)
from eval_orchestrator.domain.replay import replay


@dataclass(frozen=True)
class ReleaseReport:
    schema_version: int
    engine_version: str
    suite_id: str
    contract_sha256: str
    trace_sha256: str
    policy: Policy
    verdict: Verdict
    cases: tuple[CaseResult, ...]
    counts: dict[str, int]
    limitations: tuple[str, ...]


def evaluate_suite(suite: Suite) -> ReleaseReport:
    results = tuple(replay(case, suite.policy) for case in suite.cases)
    required = tuple(result for result in results if result.required)
    if any(result.verdict == Verdict.FAIL for result in required):
        verdict = Verdict.FAIL
    elif any(result.verdict == Verdict.INCONCLUSIVE for result in required):
        verdict = Verdict.INCONCLUSIVE
    else:
        verdict = Verdict.PASS
    return ReleaseReport(
        schema_version=1,
        engine_version=ENGINE_VERSION,
        suite_id=suite.suite_id,
        contract_sha256=suite.contract_sha256,
        trace_sha256=fingerprint(asdict(suite)),
        policy=suite.policy,
        verdict=verdict,
        cases=results,
        counts={
            "total": len(results),
            "required": len(required),
            "pass": sum(r.verdict == Verdict.PASS for r in results),
            "fail": sum(r.verdict == Verdict.FAIL for r in results),
            "inconclusive": sum(r.verdict == Verdict.INCONCLUSIVE for r in results),
            "optional_nonpassing": sum(
                not r.required and r.verdict != Verdict.PASS for r in results
            ),
        },
        limitations=(
            "Verdict applies only to supplied cases, policy and recorded events.",
            "Instrumentation authenticity and event completeness are assumed, not established.",
            "No live-model, payment-provider, statistical or regulatory-compliance claim.",
            "Optional cases remain visible but do not block release.",
        ),
    )


@dataclass(frozen=True)
class CaseDelta:
    case_id: str
    required: bool
    before: Verdict
    after: Verdict
    regression: bool
    added_codes: tuple[str, ...]
    removed_codes: tuple[str, ...]


@dataclass(frozen=True)
class Comparison:
    baseline: ReleaseReport
    candidate: ReleaseReport
    changes: tuple[CaseDelta, ...]


def compare_suites(baseline: Suite, candidate: Suite) -> Comparison:
    if baseline.contract_sha256 != candidate.contract_sha256:
        raise ValueError("Incomparable suites: policy, suite ID or scenario contracts differ")
    before, after = evaluate_suite(baseline), evaluate_suite(candidate)
    previous = {case.case_id: case for case in before.cases}
    changes = []
    rank = {Verdict.PASS: 0, Verdict.INCONCLUSIVE: 1, Verdict.FAIL: 2}
    for case in after.cases:
        old = previous[case.case_id]
        old_codes = {f.code for f in old.findings}
        new_codes = {f.code for f in case.findings}
        old_violations = {f.code for f in old.findings if f.category == "violation"}
        new_violations = {f.code for f in case.findings if f.category == "violation"}
        changes.append(
            CaseDelta(
                case.case_id,
                case.required,
                old.verdict,
                case.verdict,
                rank[case.verdict] > rank[old.verdict] or bool(new_violations - old_violations),
                tuple(sorted(new_codes - old_codes)),
                tuple(sorted(old_codes - new_codes)),
            )
        )
    return Comparison(before, after, tuple(changes))


def exit_code(verdict: Verdict) -> int:
    return {Verdict.PASS: 0, Verdict.FAIL: 1, Verdict.INCONCLUSIVE: 3}[verdict]
