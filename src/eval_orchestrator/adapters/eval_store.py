"""Exclusive, crash-aware local journals. No agent execution during evidence verification."""

import fcntl
import hashlib
import os
from pathlib import Path
from types import TracebackType
from typing import Any, BinaryIO

from eval_orchestrator.adapters.bundle import json_bytes
from eval_orchestrator.adapters.trace_json import strict_json

MAX_FILE = 64 * 1024 * 1024


def read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Expected regular artifact: {path.name}")
    with path.open("rb") as handle:
        raw = handle.read(MAX_FILE + 1)
    if len(raw) > MAX_FILE:
        raise ValueError("Artifact exceeds 64 MiB")
    # Artifacts can be larger than input definitions; duplicate keys remain forbidden.
    from json import loads

    from eval_orchestrator.adapters.trace_json import object_pairs, reject_constant

    value = loads(raw, object_pairs_hook=object_pairs, parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError("Artifact must be a JSON object")
    return value


def atomic(path: Path, raw: bytes) -> None:
    if len(raw) > MAX_FILE:
        raise ValueError("Artifact exceeds 64 MiB")
    pending = path.with_name("." + path.name + ".pending")
    if pending.is_symlink() or path.is_symlink():
        raise ValueError("Symlink artifact is not permitted")
    try:
        with pending.open("wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)


class RunStore:
    def __init__(self, directory: Path, *, create: bool = False) -> None:
        self.directory = directory.absolute()
        if create:
            self.directory.mkdir(parents=True, exist_ok=False)
        if self.directory.is_symlink() or not self.directory.is_dir():
            raise ValueError("Run must be a local real directory")
        lock_path = self.directory / "run.lock"
        if lock_path.is_symlink():
            raise ValueError("Run lock cannot be a symlink")
        self.lock: BinaryIO = lock_path.open("ab")
        try:
            fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.lock.close()
            raise ValueError("Another process holds this run; concurrent access refused") from exc

    def __enter__(self) -> "RunStore":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.lock.close()

    def initialize(self, suite: dict[str, Any], manifest: dict[str, Any]) -> None:
        (self.directory / "attempts").mkdir(exist_ok=False)
        atomic(self.directory / "suite.json", json_bytes(suite))
        atomic(self.directory / "run.json", json_bytes(manifest))

    def _path(self, slot: int, suffix: str = "json") -> Path:
        if (self.directory / "attempts").is_symlink():
            raise ValueError("Attempt directory cannot be a symlink")
        return self.directory / "attempts" / f"{slot:06d}.{suffix}"

    def load(self, slot: int) -> dict[str, Any] | None:
        path = self._path(slot)
        if not path.exists():
            return None
        if not self.started(slot):
            raise ValueError("Terminal attempt is missing its started marker")
        return read_json(path)

    def started(self, slot: int) -> bool:
        path = self._path(slot, "started.json")
        if not path.exists():
            return False
        marker = read_json(path)
        if type(marker.get("slot")) is not int or marker != {"slot": slot, "state": "started"}:
            raise ValueError("Invalid started marker")
        return True

    def start(self, slot: int) -> None:
        if self.started(slot) or self._path(slot).exists():
            raise ValueError("Attempt already started")
        atomic(self._path(slot, "started.json"), json_bytes({"slot": slot, "state": "started"}))

    def save(self, slot: int, result: dict[str, Any]) -> None:
        if not self.started(slot):
            raise ValueError("Cannot save attempt without started marker")
        if self._path(slot).exists():
            raise ValueError("Attempt already has terminal evidence")
        atomic(self._path(slot), json_bytes(result))

    def write(self, name: str, raw: bytes) -> None:
        if name not in {"report.json", "report.html", "junit.xml", "run.json"}:
            raise ValueError("Unexpected derived artifact")
        atomic(self.directory / name, raw)

    def seal(self) -> None:
        hashes = {}
        for path in sorted(self.directory.rglob("*")):
            if path.is_symlink():
                raise ValueError("Symlink in run evidence")
            if path.is_file() and path.name not in {"run.lock", "integrity.json"}:
                if path.name.endswith(".pending"):
                    raise ValueError("Incomplete atomic write remains; inspect before sealing")
                hashes[str(path.relative_to(self.directory))] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
        atomic(
            self.directory / "integrity.json", json_bytes({"schema_version": 1, "files": hashes})
        )

    def check_integrity(self) -> None:
        manifest = read_json(self.directory / "integrity.json")
        if (
            set(manifest) != {"schema_version", "files"}
            or type(manifest["schema_version"]) is not int
            or manifest["schema_version"] != 1
        ):
            raise ValueError("Invalid integrity manifest")
        files = manifest["files"]
        if not isinstance(files, dict):
            raise ValueError("Invalid integrity file list")
        actual = set()
        for path in self.directory.rglob("*"):
            if path.is_symlink():
                raise ValueError("Symlink in run evidence")
            if path.is_file() and path.name not in {"run.lock", "integrity.json"}:
                actual.add(str(path.relative_to(self.directory)))
        if actual != set(files):
            raise ValueError("Run evidence file list changed")
        for name, digest in files.items():
            path = self.directory / name
            if path.is_absolute() and (name.startswith("/") or ".." in Path(name).parts):
                raise ValueError("Invalid evidence path")
            if (
                path.stat().st_size > MAX_FILE
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest
            ):
                raise ValueError(f"Run integrity mismatch: {name}")


def load_suite_file(path: Path) -> object:
    with path.open("rb") as handle:
        return strict_json(handle.read(8 * 1024 * 1024 + 1))
