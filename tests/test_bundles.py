import hashlib
import json
import subprocess
import sys

import pytest
from test_purchasing import document, good_events

from eval_orchestrator.adapters.bundle import read_bundle, write_bundle
from eval_orchestrator.interfaces.cli import audit_files, verify_bundle


def cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "eval_orchestrator.interfaces.cli", *map(str, args)],
        capture_output=True,
        text=True,
        timeout=10,
    )


@pytest.mark.parametrize(
    "kind,expected_code,verdict",
    [
        ("pass", 0, "pass"),
        ("fail", 1, "fail"),
        ("inconclusive", 3, "inconclusive"),
    ],
)
def test_cli_audit_exit_codes_and_reproducible_bundle(tmp_path, kind, expected_code, verdict):
    data = document()
    if kind == "fail":
        data["cases"][0]["events"][3]["vendor"] = "attacker"
    elif kind == "inconclusive":
        data = document(good_events()[:3])
    source, output = tmp_path / "input.json", tmp_path / "evidence"
    source.write_text(json.dumps(data))
    result = cli("audit", "--input", source, "--output", output)
    assert result.returncode == expected_code, result.stderr
    report = json.loads((output / "report.json").read_text())
    assert report["verdict"] == verdict
    assert (output / "input.json").read_bytes() == source.read_bytes()
    assert cli("verify-bundle", output).returncode == 0
    previous = (output / "manifest.json").read_bytes()
    assert cli("audit", "--input", source, "--output", output).returncode == 2
    assert (output / "manifest.json").read_bytes() == previous


def test_bad_input_leaves_no_success_bundle(tmp_path):
    source = tmp_path / "bad.json"
    source.write_text('{"schema_version":99}')
    output = tmp_path / "evidence"
    result = cli("audit", "--input", source, "--output", output)
    assert result.returncode == 2
    assert not output.exists()


def test_cli_comparison_and_incompatible_policy(tmp_path):
    before, after = tmp_path / "before.json", tmp_path / "after.json"
    data = document()
    before.write_text(json.dumps(data))
    data["cases"][0]["events"][3]["vendor"] = "attacker"
    after.write_text(json.dumps(data))
    output = tmp_path / "comparison"
    result = cli("compare", "--baseline", before, "--candidate", after, "--output", output)
    assert result.returncode == 1
    assert "REGRESSION" in (output / "report.html").read_text()
    assert cli("verify-bundle", output).returncode == 0
    data["policy"]["budget_minor"] = 1234
    after.write_text(json.dumps(data))
    assert (
        cli(
            "compare",
            "--baseline",
            before,
            "--candidate",
            after,
            "--output",
            tmp_path / "incompatible",
        ).returncode
        == 2
    )
    assert not (tmp_path / "incompatible").exists()


def make_bundle(tmp_path):
    output = tmp_path / "bundle"
    files, _ = audit_files(json.dumps(document()).encode())
    write_bundle(output, "audit", files)
    return output


def test_changed_artifact_fails_checksum(tmp_path):
    output = make_bundle(tmp_path)
    (output / "report.json").write_text("{}")
    with pytest.raises(ValueError, match="integrity"):
        read_bundle(output)


def test_forged_report_with_rehashed_manifest_still_fails_recomputation(tmp_path):
    output = make_bundle(tmp_path)
    report_path = output / "report.json"
    report = json.loads(report_path.read_text())
    report["verdict"] = "fail"
    report_path.write_text(json.dumps(report))
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["report.json"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="reproduce"):
        verify_bundle(output)


@pytest.mark.parametrize("change", ["extra", "missing", "symlink", "traversal"])
def test_bundle_rejects_unexpected_files_and_paths(tmp_path, change):
    output = make_bundle(tmp_path)
    if change == "extra":
        (output / "extra.json").write_text("{}")
    elif change == "missing":
        (output / "report.html").unlink()
    elif change == "symlink":
        target = tmp_path / "target"
        target.write_bytes((output / "report.html").read_bytes())
        (output / "report.html").unlink()
        (output / "report.html").symlink_to(target)
    else:
        path = output / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["files"]["../target"] = manifest["files"].pop("report.html")
        path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        read_bundle(output)


def test_html_escapes_untrusted_content_and_uses_no_remote_assets():
    data = document()
    payload = '<script>alert("test")</script>'
    data["suite_id"] = payload
    data["cases"][0]["events"][3]["vendor"] = payload
    files, _ = audit_files(json.dumps(data).encode())
    rendered = files["report.html"].decode()
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "Content-Security-Policy" in rendered
    assert "https://" not in rendered


def test_failed_bundle_write_cleans_only_its_own_output(tmp_path, monkeypatch):
    from pathlib import Path

    files, _ = audit_files(json.dumps(document()).encode())
    original = Path.open

    def fail_report(path, *args, **kwargs):
        if path.name == "report.json":
            raise OSError("simulated full disk")
        return original(path, *args, **kwargs)

    output = tmp_path / "partial"
    sentinel = tmp_path / "keep.txt"
    sentinel.write_text("keep")
    monkeypatch.setattr(Path, "open", fail_report)
    with pytest.raises(OSError, match="full disk"):
        write_bundle(output, "audit", files)
    assert not output.exists()
    assert sentinel.read_text() == "keep"
