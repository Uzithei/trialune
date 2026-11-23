# Authoring task suites (schema version 1)

Tasks are JSON, with unknown fields, duplicate keys, nonfinite numbers and malformed values
rejected. Run `agent-eval validate tasks.json` before executing an agent. Use `agent-eval init`
for all 14 examples; the following is a complete minimal suite:

```json
{
  "schema_version": 1,
  "name": "invoice-checks",
  "version": "1",
  "tasks": [{
    "id": "extract-total",
    "version": "1",
    "family": "extraction",
    "required": true,
    "input": {
      "prompt": "Extract the numeric total as JSON with a total field.",
      "documents": [{"id": "invoice", "text": "Invoice 123. Total: 42"}]
    },
    "environment": {"state": {}, "tools": []},
    "checks": [{
      "id": "correct-total", "kind": "equals", "required": true,
      "pointer": "/total", "expected": 42
    }],
    "limits": {"timeout_seconds": 10, "max_tool_calls": 0}
  }]
}
```

All fields shown above are required. Families are `extraction`, `grounded_qa`, `workflow`;
these labels share the same runner and do not impose a fixed output shape. Every task needs
at least one required check; a suite needs at least one required task. Task and check IDs
must be unique within their scopes. IDs/versions use letters, digits, `.`, `_`, `-` and
begin with a letter/digit. Changes to any definition alter the suite digest and prevent
comparison with an older definition. Version identifiers also communicate intentional changes.

## Checks

Every check requires `id`, `kind`, `required`. Only the corresponding fields below are
accepted. Pointers address the returned JSON, except `state_equals` which addresses state.

| Kind | Extra fields | Pass condition |
| --- | --- | --- |
| `equals` | `pointer`, `expected` | Exact canonical JSON equality; distinguishes booleans, integers and floats |
| `text_match` | `pointer`, string `expected`, optional `casefold` | Whitespace normalized and optionally casefolded exact text |
| `answer_set` | `pointer`, string-array `expected`, optional `casefold` | Text matches one accepted answer after normalization |
| `citations` | `pointer`, string-array `allowed` | Actual array contains exactly those document IDs, no duplicates; order ignored |
| `state_equals` | `pointer`, `expected` | Observed final controlled state equals the expected value |
| `tool_policy` | None | No denied, unknown or invalid-argument calls, missing idempotency keys or key conflicts |
| `manual` | `reason` | Always unscored; a required check blocks passing |

`citations.allowed` is the exact expected set, not an optional allowlist. IDs must refer to
supplied documents. It does not assess semantic support. Broader semantic grading needs
separately qualified evaluators; use a required manual check when it is not automated.

A pointer `""` selects the entire value, `/customer/address` selects nested fields, and
`/items/0` selects an array element. Escape a literal slash as `~1` and tilde as `~0`.
Missing pointers fail. Use a whole-object `equals` check when extra fields should fail;
per-field checks allow unspecified fields. This is not a general JSON Schema validator.
Use `expected: null` for a deliberately absent value; omitting the field is different.

State and history checks still inspect observed effects after execution errors. Output
checks require completed execution. Interrupted slots with no terminal observation are
unscored. Final-state success never erases a failed required history/policy check.

## Controlled tools

The environment starts from a JSON object, reset for every trial. This example updates
an existing customer field and binds retries to an idempotency key:

```json
{
  "state": {"customers": {"c1": {"address": "Old address"}}},
  "tools": [{
    "name": "update_address",
    "description": "Update an existing customer's address.",
    "parameters": {
      "properties": {
        "customer_id": {"type": "string", "enum": ["c1"]},
        "address": {"type": "string"},
        "request_id": {"type": "string"}
      },
      "required": ["customer_id", "address", "request_id"]
    },
    "operation": "set",
    "path": "/customers/{customer_id}/address",
    "value_argument": "address",
    "idempotency_argument": "request_id",
    "allowed": true,
    "faults": [{"call": 1, "mode": "timeout_after_effect"}]
  }]
}
```

Parameter declarations support `string`, `integer`, `number`, `boolean`, `object`, `array`,
`null`, with optional `enum`. Unknown arguments and missing required arguments are rejected.
This is a deliberately limited schema, not full JSON Schema. Nested objects are JSON-bounded
but have no nested property constraints. Placeholders occupy an entire path segment and
resolve string arguments as literal keys; they cannot escape into another path.

- `read` returns the value at a pointer; empty path reads the whole state.
- `set` replaces an existing dictionary field. `value_argument` names its source parameter.
- `append` appends one value to an existing array-valued dictionary field. It cannot create
  keys, delete data or mutate array indices directly. Add distinct tools for distinct actions.
- `allowed` defaults true. A denied tool remains visible in tool descriptions so an agent's
  attempted violation can be evaluated. Include task-appropriate permission instructions.
- Optional `idempotency_argument` requires a nonempty string at execution. Its first successful
  effect caches the response. Identical retries reuse that response without another effect;
  changing arguments under the same key is a policy violation. Keys are scoped to tool/trial.
- Fault call numbers count permitted, schema-valid invocations of that tool. `error` fails
  before effect. `timeout_after_effect` executes normally but returns an ambiguous timeout;
  the next identical idempotent retry recovers the cached success. Cache replay precedes
  fault injection. Faults simulate responses, not actual wall-clock sleeps.

Add both `state_equals` and `tool_policy` when outcome and action boundaries matter. A no-op
can pass an intentionally unchanged-state task; include positive tasks so blanket refusal
cannot pass your entire suite. The starter pack supplies both positive and negative cases.

## Growing a useful corpus

Start with representative tasks from your product, scrub private data, then add failure cases
from observed incidents. Include successful work, missing information, conflicts, forbidden
actions, recoverable tool errors and retries. Check actual outcomes rather than one preferred
tool sequence. For open-ended answers, do not present narrow exact matching as full quality.
Keep a good control and a broken control for each new capability. Seeded repeats expose
observed variability but do not guarantee unseen-task reliability or statistical confidence.

Bundled examples are generated by `scripts/build_task_packs.py` into the installed package.
After editing their source, regenerate them and run the full harness. They are qualification
fixtures; product evaluation should use a separately maintained, representative corpus.
