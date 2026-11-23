"""Build offline, install the wheel into a fresh venv, exercise it outside this repo."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

from check_repository import content_problems, public_path

ROOT = Path(__file__).resolve().parents[1]


def qualify(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    environment = {**os.environ, "UV_CACHE_DIR": str(ROOT / ".cache/uv")}
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    logs: list[dict[str, object]] = []

    def run(command: list[str], cwd: Path, expected: int = 0) -> None:
        result = subprocess.run(
            command, cwd=cwd, env=environment, capture_output=True, text=True, timeout=60
        )
        logs.append(
            {
                "command": command,
                "cwd": str(cwd),
                "exit_code": result.returncode,
                "expected_exit_code": expected,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        (output / "qualification.json").write_text(json.dumps(logs, indent=2) + "\n")
        if result.returncode != expected:
            raise ValueError(f"Package check failed: {command}; {result.stderr}")

    run(["uv", "build", "--wheel", "--sdist", "--offline", "--out-dir", str(output)], ROOT)
    wheels = list(output.glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError("Expected exactly one distribution wheel")
    with zipfile.ZipFile(wheels[0]) as archive:
        members = archive.namelist()
        for name in members:
            problems = content_problems(name, archive.read(name))
            if problems:
                raise ValueError("; ".join(problems))
    if any(
        name.startswith("/")
        or ".." in Path(name).parts
        or not (name.startswith("eval_orchestrator/") or name.split("/")[0].endswith(".dist-info"))
        for name in members
    ):
        raise ValueError("Wheel contains files outside the runtime package/metadata")
    (output / "wheel-manifest.json").write_text(
        json.dumps(
            {
                "sha256": hashlib.sha256(wheels[0].read_bytes()).hexdigest(),
                "members": members,
            },
            indent=2,
        )
        + "\n"
    )
    sources = list(output.glob("*.tar.gz"))
    if len(sources) != 1:
        raise ValueError("Expected exactly one source distribution")
    source_members = []
    with tarfile.open(sources[0]) as source_archive:
        roots = set()
        for member in source_archive.getmembers():
            parts = Path(member.name).parts
            if not parts or Path(member.name).is_absolute() or ".." in parts:
                raise ValueError("Unsafe source distribution path")
            roots.add(parts[0])
            if member.isdir():
                continue
            name = "/".join(parts[1:])
            if not member.isfile() or (name != "PKG-INFO" and not public_path(name)):
                raise ValueError(f"Nonpublic source distribution member: {name}")
            handle = source_archive.extractfile(member)
            if handle is None:
                raise ValueError("Missing source distribution member")
            problems = content_problems(name, handle.read(8 * 1024 * 1024 + 1))
            if problems:
                raise ValueError("; ".join(problems))
            source_members.append(name)
        if len(roots) != 1:
            raise ValueError("Expected one source distribution root")
    (output / "sdist-manifest.json").write_text(
        json.dumps(
            {
                "sha256": hashlib.sha256(sources[0].read_bytes()).hexdigest(),
                "members": sorted(source_members),
            },
            indent=2,
        )
        + "\n"
    )
    with tempfile.TemporaryDirectory(prefix="release-wheel-") as temporary:
        scratch = Path(temporary)
        extracted = scratch / "source"
        with tarfile.open(sources[0]) as source_archive:
            source_archive.extractall(extracted, filter="data")
        source_root = next(extracted.iterdir())
        rebuilt = output / "from-sdist"
        run(["uv", "build", "--wheel", "--offline", "--out-dir", str(rebuilt)], source_root)
        rebuilt_wheels = list(rebuilt.glob("*.whl"))
        if len(rebuilt_wheels) != 1:
            raise ValueError("Source distribution did not produce a wheel")
        with (
            zipfile.ZipFile(wheels[0]) as original,
            zipfile.ZipFile(rebuilt_wheels[0]) as rebuilt_zip,
        ):
            if set(original.namelist()) != set(rebuilt_zip.namelist()) or any(
                original.read(name) != rebuilt_zip.read(name) for name in original.namelist()
            ):
                raise ValueError("Wheel rebuilt from source distribution differs from original")
        venv = scratch / "venv"
        run([sys.executable, "-m", "venv", "--without-pip", str(venv)], scratch)
        run(
            [
                "uv",
                "pip",
                "install",
                "--offline",
                "--no-deps",
                "--python",
                str(venv / "bin/python"),
                str(rebuilt_wheels[0]),
            ],
            scratch,
        )
        cli = str(venv / "bin/eval-orchestrator")
        run(
            [
                cli,
                "audit",
                "--input",
                str(ROOT / "examples/purchasing/baseline.json"),
                "--output",
                str(output / "installed-audit"),
            ],
            scratch,
        )
        run([cli, "verify-bundle", str(output / "installed-audit")], scratch)
        agent_cli = str(venv / "bin/agent-eval")
        starter = scratch / "starter"
        run([agent_cli, "init", str(starter)], scratch)
        run([agent_cli, "validate", str(starter / "starter.json")], scratch)
        for name, expected in (("good", 0), ("broken", 1)):
            destination = output / f"installed-{name}"
            run(
                [
                    agent_cli,
                    "run",
                    "--suite",
                    str(starter / "starter.json"),
                    "--agent",
                    str(starter / f"reference_{name}.py"),
                    "--output",
                    str(destination),
                ],
                scratch,
                expected,
            )
            run([agent_cli, "verify", str(destination)], scratch)
    print(f"Source rebuilt; wheel installed and verified outside source tree: {wheels[0]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    qualify(parser.parse_args().output.resolve())
