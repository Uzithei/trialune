# Contributing

The first release evaluates trusted local Python agents across extraction, grounded QA and
controlled tool workflows. Read [README](README.md), [task format](docs/task-format.md),
[integration boundaries](docs/agent-integration.md) and [architecture](docs/architecture.md) first.
No connected account, hosted service or model credential is required for development.
Participation follows the [code of conduct](CODE_OF_CONDUCT.md). Vulnerabilities should be
reported using the [security policy](SECURITY.md), not public bug reports with exploit details.

## Development loop

1. Install Python 3.12 and uv, then run `UV_CACHE_DIR=.cache/uv uv sync --locked`.
2. Describe the problem and observable acceptance criteria in the issue or pull request.
3. Run `.venv/bin/python scripts/harness.py doctor`.
4. Implement a bounded change. For a bug, reproduce the failing behavior before fixing it.
5. Run focused tests during development, then `.venv/bin/python scripts/harness.py check`.
6. Include the final evidence path and known limitations in the change description.

The full gate rejects skipped/xfail tests, dependency-boundary violations and source changes
during verification. Do not weaken these gates to pass. Coverage is diagnostic, not a claim
that every behavior was tested. Use the same command locally and in CI. The Git index must
contain the intended public files: run `git add <specific-paths>` before the full gate so its
repository check inspects the exact staged content. Review `git diff --cached` before committing.

Keep commits focused and use imperative subjects with a conventional prefix, such as
`feat: add a citation check`, `fix: preserve interrupted trials` or `docs: explain task limits`.
One logical change should include its tests and documentation. Avoid unrelated formatting
or generated artifacts. Update [CHANGELOG.md](CHANGELOG.md) for user-visible changes.

The GitHub Actions workflow runs the same gate on macOS and Linux with Python 3.12. Actions
are pinned to immutable commits, job permissions are read-only, checkout credentials are not
persisted and no publishing/upload step is configured. Initial dependency setup accesses public
package sources; the verification steps run offline. Local results do not establish that a
hosted job has run successfully.

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

`scripts/qualify_package.py --output <new-directory>` builds a wheel and source archive,
checks their contents against public-source boundaries, rebuilds the wheel from the source
archive, installs into a fresh venv and runs both CLIs outside the source tree. The full
harness includes it. `scripts/qualify_agents.py` retains passing, broken, refusal, manual
and comparison examples. None publishes to a package index.

For a bug report, include the command, runtime, smallest scrubbed task/agent, expected result,
actual result and relevant evidence. Never include secrets or sensitive raw logs. Until a
maintainer publishes a private security reporting channel, do not publish exploit details or
private evidence to an unrelated account.

## Repository and release hygiene

Keep tool code in `src/`, tests in `tests/`, examples in `examples/`, user/developer guides
in `docs/`, and maintenance commands in `scripts/`. Do not commit research, internal planning,
personal assistant instructions, generated run evidence, virtual environments or credentials.
Local-only material belongs under ignored `.local/`; root `AGENTS.md` is also local-only.

`scripts/check_repository.py` checks staged/tracked paths and common accidental secret patterns.
It is a focused guard, not a comprehensive secret scanner. Review content before sharing.
New public document names or file types require an explicit update to its allowlist. Source
archives also use an explicit include list; `.gitignore` alone is not a release boundary.

Before publishing a release: run the complete gate, inspect both archive manifests, confirm
the version/changelog, configure a private reporting channel, and review the repository's
branch protection and CI settings. A maintainer must separately authorize tagging or publishing;
the local verification commands never push, create a release or upload a package.
