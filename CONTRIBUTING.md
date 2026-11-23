# Contributing

The first release evaluates trusted local Python agents across extraction, grounded QA and
controlled tool workflows. Read [README](README.md), [task format](docs/task-format.md),
[integration boundaries](docs/agent-integration.md) and [architecture](docs/architecture.md) first.
No connected account, hosted service or model credential is required for development.

## Development loop

1. Install Python 3.12 and uv, then run `UV_CACHE_DIR=.cache/uv uv sync --locked`.
2. Describe the problem and observable acceptance criteria in the issue or pull request.
3. Run `.venv/bin/python scripts/harness.py doctor`.
4. Implement a bounded change. For a bug, reproduce the failing behavior before fixing it.
5. Run focused tests during development, then `.venv/bin/python scripts/harness.py check`.
6. Include the final evidence path and known limitations in the change description.

The full gate rejects skipped/xfail tests, dependency-boundary violations and source changes
during verification. Do not weaken these gates to pass. Coverage is diagnostic, not a claim
that every behavior was tested. Use the same command locally and in CI.

## Where changes belong

| Directory | Owns |
| --- | --- |
| `domain/` | Pure task validation, controlled environment, observation replay and grading |
| `application/` | Trial orchestration, evidence requirements and comparison policy |
| `adapters/` | Worker protocol, process supervision, storage and report rendering |
| `interfaces/` | CLI arguments and composition |
| `packs/` | Installed synthetic task definitions |
| `tests/`, `scripts/` | Behavioral checks, failure probes and release qualification |

Keep domain/application independent of filesystem, network and process APIs. Extend an
existing seam before creating more services. Do not use dynamic imports to evade boundaries.

New evaluators need a precise pass/fail/unscored contract and good/bad/missing-evidence tests.
New environments need reset, permissions, authoritative effect recording, replay and retry
qualification. New agent adapters must retain errors/timeouts/unknowns and prove cleanup.
Do not quietly replace a real grader with a stub or reinterpret absent telemetry as zero.

For new task packs, include deterministic controls that derive outputs from inputs, a wrong
agent and an abstaining agent. Use whole-state checks when duplicate effects matter. Task
content must be yours to contribute and free of credentials/private customer information.
Reference controls prove the harness works; they are not competitive benchmark results.

Changing grading, replay or report semantics requires reviewing the `ENGINE` identifier and
saved-artifact compatibility. Old artifacts should not silently change meaning. Preserve
legacy purchasing CLI compatibility unless a separately documented breaking change requires it.

## Packaging and reporting issues

`scripts/qualify_package.py --output <new-directory>` builds an offline wheel, inspects its
contents, installs into a fresh venv and runs both CLIs outside the source tree. The full
harness includes it. `scripts/qualify_agents.py` retains passing, broken, refusal, manual
and comparison examples. None publishes to a package index.

For a bug report, include the command, runtime, smallest scrubbed task/agent, expected result,
actual result and relevant evidence. Never include secrets or sensitive raw logs. Until a
maintainer publishes a private security reporting channel, do not publish exploit details or
private evidence to an unrelated account. There is no invented contact address.
