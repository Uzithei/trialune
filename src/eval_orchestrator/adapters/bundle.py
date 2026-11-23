"""Local evidence bundles and self-contained HTML. No remote assets or writes."""

import hashlib
import html
import json
import shutil
from pathlib import Path
from typing import Any

from eval_orchestrator.adapters.trace_json import fields, strict_json

FILE_SETS = {
    "audit": {"input.json", "report.json", "report.html"},
    "compare": {"baseline-input.json", "candidate-input.json", "report.json", "report.html"},
}
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_bundle(destination: Path, mode: str, files: dict[str, bytes]) -> None:
    if mode not in FILE_SETS or set(files) != FILE_SETS[mode]:
        raise ValueError("Bundle file set does not match mode")
    if any(len(raw) > MAX_ARTIFACT_BYTES for raw in files.values()):
        raise ValueError("Generated artifact exceeds 64 MiB limit")
    manifest = json_bytes(
        {
            "schema_version": 1,
            "mode": mode,
            "files": {name: digest(raw) for name, raw in files.items()},
        }
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(exist_ok=False)
    try:
        for name, raw in files.items():
            with (destination / name).open("xb") as handle:
                handle.write(raw)
        # Manifest is the completion marker, published only after every artifact exists.
        with (destination / "manifest.json").open("xb") as handle:
            handle.write(manifest)
    except BaseException:
        shutil.rmtree(destination)
        raise


def read_bundle(directory: Path) -> tuple[str, dict[str, bytes]]:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Bundle must be a real local directory")
    manifest_path = directory / "manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("Manifest cannot be a symlink")
    with manifest_path.open("rb") as handle:
        manifest = fields(
            strict_json(handle.read(65537)), {"schema_version", "mode", "files"}, "manifest"
        )
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise ValueError("Unsupported manifest version")
    mode = manifest["mode"]
    if not isinstance(mode, str) or mode not in FILE_SETS:
        raise ValueError("Unsupported bundle mode")
    hashes = fields(manifest["files"], FILE_SETS[mode], "manifest files")
    if {path.name for path in directory.iterdir()} != FILE_SETS[mode] | {"manifest.json"}:
        raise ValueError("Missing or unexpected bundle files")
    files = {}
    for name in FILE_SETS[mode]:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Bundle member must be a regular file: {name}")
        with path.open("rb") as handle:
            raw = handle.read(MAX_ARTIFACT_BYTES + 1)
        if len(raw) > MAX_ARTIFACT_BYTES or digest(raw) != hashes[name]:
            raise ValueError(f"Bundle integrity failed: {name}")
        files[name] = raw
    return mode, files


STYLE = """
:root{color-scheme:dark;font-family:system-ui,sans-serif;background:#10151d;color:#e9edf4}
*{box-sizing:border-box}body{margin:0}main{max-width:1140px;margin:auto;padding:48px 24px}
header{border-bottom:1px solid #354151;padding-bottom:30px;margin-bottom:28px}
.eyebrow{color:#94aac3;text-transform:uppercase;letter-spacing:.16em;font-size:12px}
h1{font-size:clamp(30px,5vw,48px);letter-spacing:-.04em;margin:12px 0}h2{font-size:22px}
p{line-height:1.6;color:#b5c3d4}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.card,article{background:#19212e;border:1px solid #354151;border-radius:12px;padding:20px}
.number{display:block;font-size:32px;font-weight:700;margin:8px 0}.label{color:#b5c3d4}
.badge{display:inline-block;padding:5px 10px;border-radius:6px;font-weight:650;font-size:13px}
.pass{background:#163d35;color:#7be2b7}.fail{background:#4a262f;color:#ffa4aa}
.inconclusive{background:#463b22;color:#f4d285}article{margin:16px 0}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{text-align:left;padding:12px 8px;
border-bottom:1px solid #354151;vertical-align:top}th{color:#94aac3}
code,pre{font-family:ui-monospace,monospace;font-size:12px;overflow-wrap:anywhere}
pre{white-space:pre-wrap;background:#10151d;padding:12px;border-radius:6px}
a{color:#86c3ff}summary{cursor:pointer;padding:12px 0;font-weight:600}
.warning{border-left:3px solid #f4d285;padding-left:16px}.muted{color:#94aac3;font-size:13px}
.scroll{overflow:auto}.finding{padding:12px 0;border-top:1px solid #354151}
.row{display:flex;justify-content:space-between;gap:16px;align-items:center;flex-wrap:wrap}
@media(max-width:650px){main{padding:24px 14px}.cards{grid-template-columns:repeat(2,1fr)}}
@media print{:root{color-scheme:light;background:white;color:black}p,.muted,.label{color:#333}
.card,article,pre{background:white;border-color:#888}a{color:#134e8f}details{display:block}}
"""


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def render_html(
    report: dict[str, Any],
    traces: dict[str, list[dict[str, Any]]],
    *,
    comparison: dict[str, Any] | None = None,
) -> bytes:
    badge = (
        f'<span class="badge {escape(report["verdict"])}">'
        f"{escape(report['verdict']).upper()}</span>"
    )
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">",
        f"<title>Agent Release Gate — {escape(report['suite_id'])}</title><style>{STYLE}</style>",
        "</head><body><main><header><div class='eyebrow'>Local evidence / Purchasing agents</div>",
        f"<div class='row'><h1>Agent Release Gate</h1>{badge}</div>",
        f"<p>Suite <strong>{escape(report['suite_id'])}</strong> · "
        f"Evaluator {escape(report['engine_version'])}</p>",
        "<p>Did the recorded agent respect approval boundaries and complete its task?</p>",
        "<a href='report.json'>Machine-readable report</a> · "
        "<a href='manifest.json'>Evidence manifest</a></header><section class='cards'>",
    ]
    for name, label in [
        ("total", "Recorded cases"),
        ("pass", "Passed"),
        ("fail", "Failed"),
        ("inconclusive", "Inconclusive"),
    ]:
        parts.append(
            f"<div class='card'><span class='label'>{label}</span>"
            f"<span class='number'>{report['counts'][name]}</span></div>"
        )
    parts.append("</section>")
    if report["counts"]["optional_nonpassing"]:
        parts.append(
            "<p class='warning'>Optional cases did not pass. They are included below, "
            "but do not block this release decision.</p>"
        )
    if comparison is not None:
        parts.append(
            "<h2>Baseline comparison</h2><div class='scroll'><table>"
            "<thead><tr><th>Case</th><th>Baseline → candidate</th>"
            "<th>Change</th></tr></thead><tbody>"
        )
        for delta in comparison["changes"]:
            parts.append(
                f"<tr><td>{escape(delta['case_id'])}</td>"
                f"<td>{escape(delta['before'])} → {escape(delta['after'])}</td>"
                f"<td>{'REGRESSION' if delta['regression'] else 'No regression'}"
                f"<br>{escape(', '.join(delta['added_codes']))}</td></tr>"
            )
        parts.append("</tbody></table></div>")
    parts.append("<h2>Case evidence</h2>")
    for index, case in enumerate(report["cases"]):
        events = traces[case["case_id"]]
        anchors = {entry["event_id"]: f"case-{index}-event-{n}" for n, entry in enumerate(events)}
        parts.append(
            f"<article><div class='row'><h2>{escape(case['case_id'])}</h2>"
            f"<span class='badge {escape(case['verdict'])}'>"
            f"{escape(case['verdict']).upper()}</span>"
            f"</div><p>{'Required' if case['required'] else 'Optional'} · "
            f"Observed commitments: {case['spent_minor']} {escape(report['policy']['currency'])} "
            "minor units</p>"
        )
        for finding in case["findings"]:
            links = " · ".join(
                f'<a href="#{anchors[e]}">{escape(e)}</a>'
                for e in finding["event_ids"]
                if e in anchors
            )
            parts.append(
                f"<div class='finding'><strong>{escape(finding['code'])}</strong> "
                f"<span class='muted'>{escape(finding['category'])}</span>"
                f"<p>{escape(finding['message'])}</p>{links}</div>"
            )
        if not case["findings"]:
            parts.append("<p>No violations or evidence gaps under this policy.</p>")
        parts.append("<details><summary>Inspect ordered event trace</summary>")
        for entry in events:
            parts.append(
                f"<div id='{anchors[entry['event_id']]}'><strong>"
                f"{escape(entry['event_id'])} · {escape(entry['kind'])} · {entry['at']} ms"
                f"</strong><pre>{escape(json.dumps(entry, indent=2))}</pre></div>"
            )
        parts.append("</details></article>")
    parts.append("<h2>Scope and provenance</h2><ul>")
    parts.extend(f"<li>{escape(limit)}</li>" for limit in report["limitations"])
    parts.append(
        f"</ul><p class='muted'>Contract SHA-256: <code>{report['contract_sha256']}</code>"
        f"<br>Trace SHA-256: <code>{report['trace_sha256']}</code></p></main></body></html>"
    )
    return "".join(parts).encode()
