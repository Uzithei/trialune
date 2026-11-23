# Verification contract

The harness qualifies general agent execution across three task families, plus the retained
purchasing trace checker. Qualification agents and data are synthetic. No live model,
external account, hosted service or remote publication is involved.

## Launch / Doctor / Drive / Evidence / Cleanup

- Launch: `UV_CACHE_DIR=.cache/uv uv sync --locked` creates the local environment.
- Doctor: `.venv/bin/python scripts/harness.py doctor` checks Python/tools.
- Drive: `.venv/bin/python scripts/harness.py check` exercises static checks, behavioral
  tests, negative controls, installed distributions and public CLI journeys.
- Evidence: `artifacts/verification/<UTC-time>/summary.json` records commands, exits,
  logs, runtime and source/config/docs hashes. Changes during verification invalidate it.
- Cleanup: temporary workers, scratch installs and mutated copies are removed. Local
  evidence remains. No daemon needs stopping; no previous evidence is silently deleted.

## General framework evidence

| Claim | Executable evidence | Scope |
| --- | --- | --- |
| Developer agent code actually executes | `test_agent_runner.py`, installed-wheel journey | Dedicated process; no provider adapter implied |
| Three families use one path; good/broken/refusal controls differ | CLI starter-pack test, `qualify_agents.py` | 14 synthetic tasks; not model scores |
| Expected answers/state are not supplied through context | Input visibility test | Interface separation, not hostile-code isolation |
| Tool state/history is authoritative | State-change, prose-claim and forbidden-action tests | Only provided controlled tools are observable |
| Trials start fresh | Multi-trial process/environment test | External files/services are not reset |
| Retry after ambiguous effect is idempotent | Environment recovery test and workflow pack | Declared idempotency keys, JSON state |
| Errors, deadlines, output limits, invalid protocol and call limits stay visible | Process tests in `test_agent_runner.py` | POSIX worker and bounded pipes |
| Ordinary descendants are terminated | Actual spawned-child timeout test | Not protection against deliberate process-group escape |
| Cancellation is saved and not retried | Real CLI SIGINT and resume test | Parent remains alive long enough to save evidence |
| Secrets are not inherited by default | Fake-variable isolation and opt-in forwarding test | No filesystem credential isolation/redaction |
| Unscored required criteria cannot pass | Manual-check tests, exit-3 CLI journey | Human decision recording is not implemented |
| Incomplete trials remain in denominator | Resume and consistency-summary tests | Observed pass fraction, no significance claim |
| Malformed types/numbers fail explicitly | Definition, trial-identity and extreme-duration tests | Bounded JSON; no arbitrary executable task code |
| Stored effects and grades reproduce | Run/comparison roundtrip and rehashed-forgery tests | Internal consistency, not event authenticity |
| Incompatible versions cannot compare | Changed-definition test | Whole suite/runtime/repetition settings must match |
| Prior evidence and exclusive access are protected | Overwrite, lock, changed-agent and simulated-disk-failure tests | Local filesystem; no database transaction service |
| Installed package includes tasks and examples | `qualify_package.py` | Fresh venv outside source, both CLIs and negative agent |
| Public Git content excludes local notes and common secret patterns | `test_repository.py`, `check_repository.py` | Reads staged bytes; focused pattern checks are not exhaustive secret detection |
| Source releases contain only approved public files | `qualify_package.py` | Archive inspection, identical wheel rebuild from source, clean installation |
| Public CLI supports pass/fail/unknown and comparisons | `qualify_agents.py` | Retained JSON/HTML/JUnit and execution logs |

## Legacy purchasing evidence

`test_purchasing.py`, `test_replay_edges.py`, `test_release.py` and `test_bundles.py`
cover authorization binding/revocation, event ordering, budgets, duplicate purchases,
missing evidence, compatible comparisons, invalid input, escaped reports and bundle replay.
`qualify_release.py` exercises passing, failing and incomplete traces via the legacy CLI.
Those tests do not imply a real purchasing integration or live payment execution.

## Shared gates and interpretation

- Offline lock/environment validation, Ruff lint/format, strict mypy and AST dependency
  boundaries. Domain/application cannot import infrastructure. This is not sandboxing.
- Nine deliberately broken variants must be caught by assertions or the architecture gate:
  wrong agent output, ignored forbidden calls, falsely passing unscored checks, revoked
  approval, duplicate purchase, dropped case, partial evidence, reversed score threshold,
  and an illegal infrastructure import. These are selected probes, not exhaustive mutations.
- Tests cannot silently skip, xfail or xpass. The test-process socket guard does not isolate
  subprocesses/native code. Default examples contain no network clients.
- Coverage is diagnostic; subprocess-only code is exercised by exits and artifacts but is
  not included in parent-process line coverage. A percentage is not a safety score.
- Final evidence is tied to source files, not signed. Keep evidence under trusted ownership.
  Regression verification does not prove a framework or agent can never fail.

The [CI workflow](../.github/workflows/ci.yml) targets macOS and Linux using this same gate.
Its actions are pinned, permissions are read-only and it does not publish packages or upload
run bundles. A local passing gate is not evidence of a hosted CI run or another OS passing.

## Unverified or out of scope

Live model/provider compatibility, model stochasticity, Windows, hostile-code isolation,
token/cost attribution, semantic model judges, native
Inspect/garak imports, browser/HTTP targets, concurrent distributed execution, multi-user
authorization, hosted deployment and compliance certification.

When a defect is found: retain the reproducer, assert expected observable behavior, fix the
root cause and rerun the relevant boundary before the full gate. Update this map when adding
a boundary. Never label an unavailable or failed check as passing.
