# Agent Evaluation Framework

**Run your agent on repeatable tasks. Check its answers and actual tool effects. Catch
regressions before you ship a change.**

For example: a support agent says it updated a customer's address. This framework checks
whether the controlled customer record actually changed, whether permitted tools were used,
and whether the agent still succeeds after a tool timeout. Test a new prompt or model on
the same tasks and compare it with the previous version.

The CLI executes a Python agent you supply. You write tasks and success criteria; the runner
collects evidence automatically. No manually prepared conversation traces are needed.

| Task family | Starter examples | What is checked |
| --- | --- | --- |
| Extraction / classification | Invoice fields, missing totals, support labels | Exact JSON values or normalized text |
| Grounded QA | Supplied documents, absent/conflicting information | Bounded reference answers, explicit abstention, citation IDs |
| Tool workflows | Read an order, change an address, cancel a subscription, retry a timeout | Actual state, permissions, valid arguments, duplicate effects |

Version **0.2.0** includes 14 synthetic tasks, deterministic good/broken/refusal agents,
repeated trials, deadlines, crash-aware resume, HTML/JSON/JUnit reports and verifiable
comparisons. The examples qualify the framework; they are not live-model benchmarks.
Requires Python 3.12 and POSIX (macOS or Linux). Windows is not supported.
There are no third-party runtime dependencies.

## Try it locally

From this repository, with Python 3.12 and `uv` installed:

```sh
UV_CACHE_DIR=.cache/uv uv sync --locked
.venv/bin/agent-eval init artifacts/my-evaluation
.venv/bin/agent-eval validate artifacts/my-evaluation/starter.json
.venv/bin/agent-eval run \
  --suite artifacts/my-evaluation/starter.json \
  --agent artifacts/my-evaluation/reference_good.py \
  --repeats 3 --output artifacts/my-baseline
.venv/bin/agent-eval verify artifacts/my-baseline
```

Open `artifacts/my-baseline/report.html`. All 42 trials should pass. Expand a trial to see
the answer, tool calls, results, final state and logs. The run retains task definitions,
an entrypoint fingerprint, individual attempts and machine-readable results.

Now run an intentionally broken candidate:

```sh
.venv/bin/agent-eval run \
  --suite artifacts/my-evaluation/starter.json \
  --agent artifacts/my-evaluation/reference_broken.py \
  --repeats 3 --output artifacts/my-candidate
.venv/bin/agent-eval compare \
  --baseline artifacts/my-baseline --candidate artifacts/my-candidate \
  --output artifacts/my-comparison
.venv/bin/agent-eval verify artifacts/my-comparison
```

The broken run and comparison intentionally exit **1**. Open
`artifacts/my-comparison/comparison.html` for regressions. `verify` exits 0 when evidence
is internally consistent, even if the agent failed. Choose a new output directory each run;
completed evidence cannot be overwritten.

Default examples need no credentials or network calls. Initial dependency installation
downloads public packages unless cached. Nothing is uploaded by the runner.

## Bring your agent

Create a Python file containing `run(context)`. Pass `context.prompt` and
`context.documents` to your agent and return a JSON-compatible answer. For workflows,
route selected tools through `context.call_tool(name, arguments)`; the parent runner owns
and observes their effects. Every trial starts a fresh process and environment.

```python
# Integration sketch: my_application is your code, not a bundled dependency.
from my_application import agent


def run(context):
    return agent.evaluate_task(
        prompt=context.prompt,
        documents=context.documents,
        tools=context.tools,
        call_tool=context.call_tool,
        seed=context.seed,
    )
```

Install your agent's dependencies in the same environment and replace `--agent` with your
file. Edit the copied JSON tasks or author your own; the runner does not depend on starter
task IDs. See [integration](docs/agent-integration.md) and [task authoring](docs/task-format.md).

## Decisions and evidence

| Outcome | CLI exit | Meaning |
| --- | --- | --- |
| Pass | 0 | Every required trial and check passed |
| Fail | 1 | A required criterion failed |
| Invalid operation | 2 | Definition, IO, compatibility or verification error |
| Inconclusive | 3 | Required evidence is missing, with no required failure |
| Operator interruption | 130 | Available terminal observations saved; resume can continue |

Optional failures stay visible. Errors and interruptions stay in trial counts. Required
manual checks remain unscored and block a pass. Citation checks validate IDs, not semantic
support. There is no averaged score that can hide a required failure.

```sh
.venv/bin/agent-eval resume artifacts/interrupted-run --agent my_agent.py
```

Resume reuses completed trials and runs only unstarted ones. Started trials without terminal
evidence become interrupted/inconclusive; they are never secretly retried. Comparisons require
matching tasks, checks, environments, limits, repeats, seed and runtime. Reported changes are
observations, not statistical significance.

## Engineering and boundaries

```sh
.venv/bin/python scripts/harness.py doctor
.venv/bin/python scripts/harness.py check
```

The offline gate checks locked dependencies, lint/format, strict types, architecture,
behavioral tests, nine deliberately broken variants, complete CLI journeys and release
packages installed outside the source tree. Logs, coverage, packages and source fingerprints
stay under `artifacts/verification/`. See [verification](docs/verification.md) for details.

Run **trusted agent code**. Process separation is not a hostile-code sandbox: agents can
access files/network under your OS user. Tools bypassing the context are unobserved.
Credentials are not forwarded by default; opt-in values can still leak through agent logs.
Token usage and cost remain unknown. Read the [operational limits](docs/agent-integration.md#operational-limits).

| Resource | Purpose |
| --- | --- |
| [Architecture](docs/architecture.md) | Module boundaries and execution design |
| [Verification map](docs/verification.md) | Claims tied to executable evidence |
| [Contributing](CONTRIBUTING.md) | Add qualified tasks, checks and adapters |
| [Legacy purchasing](docs/purchasing-guide.md) | Optional trace auditing via `eval-orchestrator` |

Licensed under [MIT](LICENSE). Install from source using the instructions above; no package-index
release is assumed. Hosted services, HTTP agents, browser tasks, semantic model judges and
vendor adapters are not included.
