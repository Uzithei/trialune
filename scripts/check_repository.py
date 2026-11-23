"""Check the Git index for public source boundaries and common accidental disclosures."""

import re
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    "README.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "LICENSE",
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
}
DOCS = {
    "architecture.md",
    "agent-integration.md",
    "task-format.md",
    "trace-format.md",
    "purchasing-guide.md",
    "verification.md",
}
TREES = {
    "src": {".py", ".json"},
    "tests": {".py"},
    "scripts": {".py"},
    "fixtures": {".json"},
    "examples": {".json", ".md", ".py"},
    ".github": {".md", ".yml", ".yaml"},
}
PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "access token": re.compile(r"(?:sk-(?:proj-)?|gh[pousr]_|github_pat_)[A-Za-z0-9_-]{20,}"),
    "cloud access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "personal filesystem path": re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+/"),
}


def public_path(name: str) -> bool:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or str(path) != name:
        return False
    if name in ROOT_FILES:
        return True
    if len(path.parts) < 2 or any(
        part.startswith(".") or part in {"__pycache__", "AGENTS.md"} for part in path.parts[1:]
    ):
        return False
    if path.parts[0] == "docs":
        return len(path.parts) == 2 and path.name in DOCS
    return path.suffix in TREES.get(path.parts[0], set())


def content_problems(name: str, raw: bytes) -> list[str]:
    if len(raw) > 8 * 1024 * 1024:
        return [f"{name}: public text file exceeds 8 MiB"]
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        return [f"{name}: expected UTF-8 source, not a binary artifact"]
    return [
        f"{name}: possible {label}; inspect locally"
        for label, regex in PATTERNS.items()
        if regex.search(content)
    ]


def check_index(root: Path) -> tuple[int, list[str]]:
    result = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    entries = [entry for entry in result.stdout.split(b"\0") if entry]
    if not entries:
        return 0, ["No staged/tracked source; stage the intended public files before checking"]
    errors = []
    for entry in entries:
        meta, raw_name = entry.split(b"\t", 1)
        mode, blob, stage = meta.decode().split()
        name = raw_name.decode()
        if mode not in {"100644", "100755"} or stage != "0":
            errors.append(f"{name}: links, submodules and unresolved entries are not public source")
            continue
        if not public_path(name):
            errors.append(f"{name}: outside the public source allowlist")
            continue
        raw = subprocess.run(
            ["git", "cat-file", "blob", blob],
            cwd=root,
            capture_output=True,
            check=True,
        ).stdout
        errors.extend(content_problems(name, raw))
    return len(entries), errors


def main() -> int:
    try:
        count, errors = check_index(ROOT)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"Repository check failed: {exc}")
        return 1
    print(
        "\n".join(errors) if errors else f"Public repository boundary passed: {count} indexed files"
    )
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
