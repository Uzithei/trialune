# Synthetic purchasing demonstrations

These are authored engineering examples, not captured customer/model runs.

| Corpus | Expected result |
| --- | --- |
| `baseline.json` | Three passes: approved purchase, safe retry, safe cancellation; exit 0 |
| `candidate.json` | Altered payee and duplicate retry effect; exit 1, two regressions |
| `incomplete.json` | First purchase lacks outcome and terminal event; exit 3 |

Run `.venv/bin/python scripts/qualify_release.py --output <new-directory>` to exercise all
three through the installed CLI, compare baseline/candidate, and verify all four bundles.
No models or accounts are involved. The evaluator accepts arbitrary valid corpora and does
not select verdicts by these filenames.
