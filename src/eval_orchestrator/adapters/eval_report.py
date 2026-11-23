"""Standalone HTML and CI-compatible JUnit for general agent evaluations."""

import html
import json
import xml.etree.ElementTree as ET
from typing import Any

from eval_orchestrator.adapters.bundle import STYLE


def render(report: dict[str, Any]) -> bytes:
    def esc(value: object) -> str:
        return html.escape(str(value), quote=True)

    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">",
        f"<title>Agent evaluation — {esc(report['suite_name'])}</title><style>{STYLE}</style>",
        "</head><body><main><header><div class='eyebrow'>Agent evaluation / local evidence</div>",
        f"<div class='row'><h1>{esc(report['suite_name'])}</h1>"
        f"<span class='badge {report['verdict']}'>{report['verdict'].upper()}</span></div>",
        f"<p>Agent: {esc(report['agent']['entrypoint'])} · "
        f"{report['repeats']} trial(s) per task</p>",
        "<p>Execution, task correctness, tool effects and missing evidence are separate.</p>",
        "<a href='report.json'>JSON</a> · <a href='junit.xml'>JUnit</a> · "
        "<a href='suite.json'>Task definitions</a></header><section class='cards'>",
    ]
    for key in ("total", "pass", "fail", "inconclusive"):
        parts.append(
            f"<div class='card'><span class='label'>{key.title()}</span>"
            f"<span class='number'>{report['counts'][key]}</span></div>"
        )
    parts.append(
        "</section><h2>Consistency across trials</h2><div class='scroll'><table>"
        "<tr><th>Task</th><th>Passed / trials</th><th>Mean runtime</th></tr>"
    )
    for summary in report["task_summary"]:
        duration = summary["mean_duration_ms"]
        runtime = "Unknown" if duration is None else f"{duration:.2f} ms"
        parts.append(
            f"<tr><td>{esc(summary['task_id'])}</td>"
            f"<td>{summary['passed']} / {summary['trials']}</td>"
            f"<td>{runtime} ({summary['observed_duration_trials']} measured)</td></tr>"
        )
    parts.append(
        "</table></div><p class='muted'>Observed trial counts, not a statistical guarantee. "
        "Errors and missing assessments remain in the denominator.</p><h2>Trials and evidence</h2>"
    )
    for attempt in report["attempts"]:
        observation = attempt["observation"]
        runtime = (
            "Unknown runtime"
            if observation["duration_ms"] is None
            else f"{observation['duration_ms']} ms"
        )
        parts.append(
            f"<article><div class='row'><h2>{esc(attempt['task_id'])} "
            f"· trial {attempt['trial'] + 1}</h2><span class='badge {attempt['verdict']}'>"
            f"{attempt['verdict'].upper()}</span></div><p>{esc(attempt['family'])} · "
            f"{'Required' if attempt['required'] else 'Optional'} · "
            f"Execution: {esc(observation['execution'])} · {runtime} · "
            f"{observation['tool_calls']} tool calls</p>"
        )
        if observation["error"]:
            parts.append(f"<p class='warning'>{esc(observation['error'])}</p>")
        parts.append(
            "<div class='scroll'><table><tr><th>Check</th><th>Result</th><th>Evidence</th></tr>"
        )
        for check in attempt["checks"]:
            parts.append(
                f"<tr><td>{esc(check['id'])}<br><small>"
                f"{'Required' if check['required'] else 'Optional'}</small></td>"
                f"<td>{esc(check['status'])}</td><td>{esc(check['message'])}"
                f"<pre>{esc(json.dumps(check['evidence'], indent=2, sort_keys=True))}</pre>"
                "</td></tr>"
            )
        parts.append(
            "</table></div><details><summary>Output, tool history and final state</summary>"
        )
        parts.append(
            f"<pre>{esc(json.dumps(observation, indent=2, sort_keys=True))}</pre>"
            "</details></article>"
        )
    parts.append("<h2>Scope</h2><ul>")
    parts.extend(f"<li>{esc(limit)}</li>" for limit in report["limitations"])
    parts.append(
        f"</ul><p class='muted'>Configuration: <code>{report['configuration_sha256']}</code>"
        f"<br>Agent entrypoint: <code>{report['agent']['sha256']}</code></p></main></body></html>"
    )
    return "".join(parts).encode()


def junit(report: dict[str, Any]) -> bytes:
    attempts = report["attempts"]
    root = ET.Element(
        "testsuite",
        name=report["suite_name"],
        tests=str(len(attempts)),
        failures=str(sum(a["required"] and a["verdict"] == "fail" for a in attempts)),
        errors=str(sum(a["required"] and a["verdict"] == "inconclusive" for a in attempts)),
        skipped=str(sum(not a["required"] and a["verdict"] != "pass" for a in attempts)),
    )
    for attempt in attempts:
        case = ET.SubElement(
            root,
            "testcase",
            name=f"{attempt['task_id']}[{attempt['trial']}]",
            classname=attempt["family"],
        )
        if attempt["observation"]["duration_ms"] is not None:
            case.set("time", str(attempt["observation"]["duration_ms"] / 1000))
        if attempt["verdict"] != "pass":
            tag = (
                "skipped"
                if not attempt["required"]
                else "failure"
                if attempt["verdict"] == "fail"
                else "error"
            )
            ET.SubElement(case, tag, message=f"Evaluation {attempt['verdict']}").text = json.dumps(
                attempt["checks"], sort_keys=True
            )
        ET.SubElement(case, "system-out").text = json.dumps(attempt["observation"], sort_keys=True)
    output = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    assert isinstance(output, bytes)
    return output


def comparison_html(comparison: dict[str, Any]) -> bytes:
    esc = html.escape
    rows = []
    for change in comparison["changes"]:
        rows.append(
            f"<tr><td>{esc(change['task_id'])} [{change['trial'] + 1}]</td>"
            f"<td>{change['before']} → {change['after']}</td>"
            f"<td>{'Observed regression' if change['regression'] else 'No new regression'}"
            f"<br>{esc(', '.join(change['new_failures']))}</td></tr>"
        )
    page = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">"
        f"<title>Agent comparison</title><style>{STYLE}</style></head><body><main>"
        "<header><div class='eyebrow'>Agent evaluation / version comparison</div>"
        f"<h1>Candidate: {comparison['verdict'].upper()}</h1>"
        f"<p>{esc(comparison['baseline_agent']['entrypoint'])} → "
        f"{esc(comparison['candidate_agent']['entrypoint'])}</p>"
        "<a href='comparison.json'>Comparison JSON</a> · "
        "<a href='baseline-report.json'>Baseline evidence</a> · "
        "<a href='candidate-report.json'>Candidate evidence</a></header>"
        "<div class='scroll'><table><tr><th>Task / trial</th><th>Verdict</th><th>Change</th></tr>"
        + "".join(rows)
        + "</table></div><p>Matching task, evaluator, runtime and repetition "
        "contracts. Transitions are observations, not proof of statistical significance. "
        "An inconclusive result remains unresolved.</p></main></body></html>"
    )
    return page.encode()
