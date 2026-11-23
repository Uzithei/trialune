import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "repository_policy", ROOT / "scripts/check_repository.py"
)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


@pytest.mark.parametrize(
    "path",
    [
        ".local/notes.md",
        "AGENTS.md",
        "research.md",
        "docs/research.md",
        "artifacts/report.json",
        "src/.env",
        "src/package/credential.pem",
        "../README.md",
        "/README.md",
        "src/package/__pycache__/cached.py",
        "src/package/AGENTS.md",
    ],
)
def test_private_material_is_outside_public_boundary(path):
    assert not policy.public_path(path)


def test_public_tool_files_are_allowed():
    for path in [
        "README.md",
        "LICENSE",
        "src/package/main.py",
        "tests/test_cli.py",
        "docs/architecture.md",
        ".github/workflows/ci.yml",
    ]:
        assert policy.public_path(path)


def test_common_secret_patterns_are_reported_without_echoing_values():
    token = "ghp_" + "x" * 30
    errors = policy.content_problems("src/config.py", token.encode())
    assert errors and "access token" in errors[0]
    assert token not in errors[0]


def test_index_check_inspects_staged_bytes_not_cleaned_worktree(tmp_path):
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    source = tmp_path / "README.md"
    source.write_text("ghp_" + "x" * 30)
    git("add", "README.md")
    source.write_text("Clean working copy")
    count, errors = policy.check_index(tmp_path)
    assert count == 1
    assert any("access token" in error for error in errors)
    git("add", "README.md")
    assert policy.check_index(tmp_path) == (1, [])


def test_force_added_private_files_and_symlinks_are_rejected(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "AGENTS.md").write_text("Local policy")
    (tmp_path / "README.md").symlink_to("AGENTS.md")
    subprocess.run(["git", "add", "AGENTS.md", "README.md"], cwd=tmp_path, check=True)
    count, errors = policy.check_index(tmp_path)
    assert count == 2
    assert len(errors) == 2
