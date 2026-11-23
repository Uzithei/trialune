import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("harness", ROOT / "scripts/harness.py")
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


def test_fingerprint_tracks_source_but_not_generated_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    source = tmp_path / "example.py"
    source.write_text("x = 1\n")
    before = harness.snapshot()
    for directory in ("artifacts", ".cache", ".venv", ".local", ".codex", ".agents"):
        generated = tmp_path / directory
        generated.mkdir()
        (generated / "output.json").write_text('{"generated": true}')
    assert harness.snapshot() == before
    (tmp_path / "AGENTS.md").write_text("Personal local instructions")
    assert harness.snapshot() == before
    workflow = tmp_path / ".github/workflows"
    workflow.mkdir(parents=True)
    (workflow / "ci.yml").write_text("name: CI\n")
    assert harness.snapshot() != before
    before = harness.snapshot()
    source.write_text("x = 2\n")
    assert harness.snapshot() != before


def test_linter_excludes_downloaded_cache_even_outside_git(tmp_path):
    (tmp_path / "pyproject.toml").write_text((ROOT / "pyproject.toml").read_text())
    cache = tmp_path / ".cache"
    cache.mkdir()
    (cache / "third_party.py").write_text("this is intentionally invalid python!\n")
    source = tmp_path / "example.py"
    source.write_text('"""Valid project code."""\n')
    command = [sys.executable, "-m", "ruff", "check", "."]
    assert subprocess.run(command, cwd=tmp_path, capture_output=True, timeout=10).returncode == 0
    source.write_text("this is intentionally invalid python!\n")
    assert subprocess.run(command, cwd=tmp_path, capture_output=True, timeout=10).returncode != 0
