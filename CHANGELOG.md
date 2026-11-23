# Changelog

User-visible changes are recorded here. The initial public release is being prepared as
version `0.2.0`; no release tag or package-index publication is implied.

## Unreleased

### Added

- Local `agent-eval` CLI for extraction, grounded QA and controlled tool workflows.
- Strict task definitions, 14 synthetic starter tasks and good/broken/refusal controls.
- Dedicated worker processes, tool-state isolation, deadlines and bounded protocol IO.
- Repeated trials, crash-aware journals, explicit unknown assessments and compatible comparisons.
- Replayable evidence with JSON, standalone HTML and JUnit reports.
- Optional purchasing trace audit through `eval-orchestrator`.
- Offline verification, negative defect probes, public-source boundary checks and release
  qualification from both wheel and source distribution.
- Contributor and security policies, issue/PR templates and CI for macOS and Linux.

### Known limits

- Python 3.12 and POSIX only; no hostile-code sandbox.
- Deterministic checks; no semantic model judge, provider adapter or measured token/cost data.
- No hosted service, HTTP/browser agent runner or distributed execution.
