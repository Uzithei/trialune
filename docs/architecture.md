# Architecture

The framework is a local Python application with a CLI, one subprocess per agent trial,
controlled JSON-state tools and filesystem evidence. It has no runtime service dependencies.

```text
agent-eval CLI
  └─ application: schedule trials and decide outcomes
       ├─ process adapter: execute trusted agent code
       │    └─ worker: run(context), tool requests, final output
       ├─ domain: own tool state, replay events, grade observations
       └─ storage/report adapters: journal, JSON, HTML, JUnit
```

## Boundaries

| Layer | Responsibilities | May import |
| --- | --- | --- |
| `domain` | Immutable task definitions, environments, replay and deterministic grading | Domain and approved pure standard library modules |
| `application` | Trial scheduling, required evidence, run verdicts and comparisons | Application and domain |
| `adapters` | Process IO, worker interface, local storage, parsing and reports | Adapters, domain and infrastructure |
| `interfaces` | CLI composition, arguments and exit codes | All layers |

`scripts/check_architecture.py` enforces ordinary import boundaries. It is a maintenance
constraint, not a security sandbox. Application code receives runner/store implementations
through small protocols rather than importing their infrastructure.

## Trial lifecycle

1. Validate and freeze a task suite; fingerprint the agent entrypoint and run settings.
2. Acquire an exclusive run lock and create a started marker for the next scheduled slot.
3. Start a worker with fresh process-local state, a temporary directory and an allowlisted
   environment. Send task inputs and tool descriptions, without reference checks.
4. Handle tool requests in the parent. Validate arguments, apply effects and record events.
5. Capture execution status, output, stderr, observed runtime and final state; enforce limits.
6. Replay and grade the observation. Retain each check and every scheduled trial.
7. Write atomic terminal evidence; generate aggregate reports and an integrity manifest.

The worker protocol uses bounded JSON lines over pipes. User code exposes `run(context)`;
tool invocations go through `context.call_tool`. Exceptions and interrupted execution do not
become successful assessments. Process-group termination handles ordinary child processes,
but does not isolate hostile code from the host filesystem or network.

## Assessment and recovery

Checks distinguish task correctness, observed action history and missing evidence. Required
failures block release; missing required checks are inconclusive. Optional results remain
visible. Unknown cost, token usage and interrupted duration are never fabricated.

Resume reuses validated terminal records. Started slots without terminal evidence become
interrupted/inconclusive, and only unstarted slots execute. This avoids silently retrying
uncertain effects. Verification replays retained observations and regenerates reports without
running the agent. Hashes establish internal consistency, not authenticity.

Comparisons require compatible suite/evaluator/runtime/repetition settings. Their evidence
contains both source reports and definitions, so the comparison can be verified independently.

## Extensions

New graders belong in the domain with explicit fail/unscored semantics. New environments
must preserve reset, permission and authoritative-effect behavior. New process or endpoint
adapters must qualify timeout, cancellation, observability and cleanup. Add abstractions when
a second concrete implementation needs them; a distributed queue or server is not required
for adding a task pack.

The optional `eval-orchestrator` CLI retains the purchasing trace evaluator and original
fixture checks. It shares package infrastructure but does not define the general task model.
See [integration](agent-integration.md), [tasks](task-format.md) and
[verification](verification.md) for exact supported behavior and limits.
