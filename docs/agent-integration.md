# Integrating and operating an agent

## Agent contract

Use `agent-eval run --suite tasks.json --agent my_agent.py --output artifacts/run-001`.
Expose a synchronous `run(context)` function returning JSON data. Async applications can
call `asyncio.run()` inside it. Install provider/framework dependencies in the CLI's Python
environment. Sibling imports resolve relative to the original agent file; execution uses a
temporary working directory, so use explicit paths for other resources.

| Member | Meaning |
| --- | --- |
| `task_id` | Stable task identifier |
| `prompt` | Instruction string |
| `documents` | Supplied `{id, text}` records |
| `tools` | Tool names, descriptions and parameter declarations |
| `trial` | Zero-based repetition |
| `seed` | Run seed plus trial number; your adapter must apply it |
| `call_tool(name, arguments)` | Returns `{ok, value}` or `{ok: false, error}` |

The interface does not send check definitions, expected answers, hidden initial state,
permission flags or fault schedules to the agent. This avoids accidental leakage, but cannot
protect local files from hostile code. `print()` goes to captured stderr. Direct protocol
stdout writes are invalid. Context tool calls must be sequential, not concurrent.

For model tool use: translate the tool parameters into your provider's schema, call the
model, execute its selections through `context.call_tool`, pass results back to the model,
and return its final answer. Preserve tool errors. Calls bypassing the context are not
observed. No provider adapter or automatic tool-schema conversion is included.

The entrypoint bytes are snapshotted and hashed. Imported modules, external models, remote
data, dependency packages and other files are **not** frozen. Pin these in your application
and record external provenance separately. Seeds do not guarantee provider determinism.

## Environment and credentials

Only `PATH`, `LANG`, `LC_ALL`, `TZ` and internal Python IO settings are inherited by default.
Explicit forwarding is available for services/accounts you independently own and authorize:

```sh
agent-eval run --suite tasks.json --agent my_agent.py --output artifacts/run-002 \
  --env MY_AGENT_API_KEY
```

The variable must exist. Interpreter/loader overrides are rejected. Manifests retain names,
never values, but agents can print secrets or return them; artifacts are not automatically
redacted. Agents can also access local credential files. Inspect evidence before sharing.
Resume with forwarded variables is refused because values are not fingerprinted; use a fresh
run. This example does not authorize access to any external account.

## Release decisions and comparisons

A required failed check fails its trial. Missing required checks or incomplete execution
make it inconclusive if no required check failed. All required trials must pass; optional
failures remain visible. Comparisons require matching suite digest, evaluator version,
repeat count, seed, Python version and platform; entrypoints may differ.

The comparison retains both definitions, manifests and reports. `verify` replays their tool
events and rescores their outcomes. Worsened verdicts and newly failed checks are highlighted,
including new failures in an already-failing trial. Its exit follows the candidate verdict;
optional regressions are visible but do not block it. No statistical significance test or
thresholded performance comparison is implemented.

## Recovery and retained evidence

An exclusive `run.lock` protects each run. Stable slots are scheduled task-first, then trial.
A started marker precedes execution and a terminal observation follows it. Atomic file
replacement avoids partially replacing a prior record. Abrupt termination may leave an
incomplete directory or `.pending` file; inspect it before removing anything.

`resume` requires the same entrypoint name/hash and runtime. It regrades saved attempts,
runs unstarted slots and records missing terminal observations as interrupted/inconclusive.
It never reruns uncertain work automatically. Ctrl-C saves a cancelled observation when
supervision is active; a second interrupt or abrupt kill may leave only a started marker.
An unobserved interrupted attempt has `duration_ms: null`; mean runtime includes only
measured trials and states that denominator. It still counts in the pass-fraction denominator.

```text
run.json                  execution identity, settings, runtime and completion state
suite.json                frozen tasks and expectations
attempts/000000.started.json
attempts/000000.json       output, tool history/state, checks and verdict for one slot
report.json               all trials, counts, per-task observed pass fractions
report.html               standalone HTML with escaped content; no remote assets/scripts
junit.xml                 required failures/errors; optional nonpasses are skipped cases
integrity.json            exact file list and SHA-256 hashes
run.lock
```

`verify` checks inventory/hashes, replays tool effects and regenerates assessments and
JSON/HTML/JUnit. No agent or model executes. This establishes internal consistency, not
authenticity: replacing all inputs/evidence consistently can produce another valid bundle.
Keep originals in your own trusted storage. Files use normal umask permissions; use a
private directory for sensitive tasks. No encryption, signatures or retention service exists.

## Operational limits

- Python 3.12, macOS/Linux POSIX APIs; Windows is unsupported.
- Trusted code only. No filesystem, network, CPU or memory sandbox. Process-group cleanup
  kills ordinary descendants; hostile code can escape the group and needs external isolation.
- Sequential execution: at most 500 tasks, 100 repeats and 1000 attempts per run.
- Task worker deadlines 0.05–300 seconds, 0–1000 tool calls. Startup, parent bookkeeping
  and cleanup add overhead. Remote billing may continue after local process termination.
- Protocol message limit 256 KiB; stdout/stderr 1 MiB each; trace limit 4 MiB, checked after
  tool execution. The last actual effect remains evidence even on a size-limit stop.
- Suite limit 8 MiB; entrypoint 1 MiB; evidence file 64 MiB. Split large runs. JSON nesting
  limit 32, strings 100,000 characters, arrays/objects 10,000 entries. Numbers must be finite
  within ±(2^53−1). Booleans are distinct from numbers.
- Controlled JSON-state read/set/append tools model test backends. They do not connect to
  real customer databases. Task definitions cannot contain executable code.
- Runtime/calls are measured; tokens/cost are `null`. No automatic retries, remote queue,
  concurrent tool dispatch, multi-user server or normalized provider traces.
- Citation/exact-answer checks are bounded checks, not universal factuality grading.
  Manual checks remain unscored; recording human review decisions is not implemented.
- File flush/atomic replacement protect ordinary writes. Directory metadata power-loss
  durability is not guaranteed. Hashes are not signatures.

Companies can evaluate their trusted agents locally or in CI. They remain responsible for
external integration and representative tasks. Synthetic qualification does not measure
live-model behavior.
