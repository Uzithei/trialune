"""Bounded POSIX process transport, with parent-owned tool execution and evidence."""

import hashlib
import os
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from eval_orchestrator.adapters.trace_json import strict_json
from eval_orchestrator.domain.environment import Environment
from eval_orchestrator.domain.tasks import Task, canonical, json_data, obj

MAX_MESSAGE = 262144
MAX_STREAM = 1048576
MAX_TRACE = 4194304


def empty_observation(task: Task, execution: str, reason: str) -> dict[str, Any]:
    return {
        "execution": execution,
        "output": None,
        "events": [],
        "final_state": task.spec["environment"]["state"],
        "duration_ms": 0.0,
        "tool_calls": 0,
        "usage": None,
        "cost": None,
        "error": reason,
        "stderr": "",
    }


class ProcessAgent:
    def __init__(self, path: Path, forwarded_env: tuple[str, ...] = ()) -> None:
        if os.name != "posix":
            raise ValueError("Process runner currently supports macOS and Linux")
        self.path = path.resolve(strict=True)
        if not self.path.is_file() or self.path.stat().st_size > MAX_STREAM:
            raise ValueError("Agent must be a Python file up to 1 MiB")
        self.source = self.path.read_bytes()
        self.digest = hashlib.sha256(self.source).hexdigest()
        self.forwarded_env = forwarded_env
        if len(set(forwarded_env)) != len(forwarded_env):
            raise ValueError("Duplicate forwarded environment variable")
        for key in forwarded_env:
            if not key.isidentifier() or key not in os.environ:
                raise ValueError(f"Explicit environment variable missing or invalid: {key}")
            if key.startswith("PYTHON") or key.startswith("DYLD") or key.startswith("LD_"):
                raise ValueError("Interpreter and loader environment overrides are not supported")

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "entrypoint": self.path.name,
            "sha256": self.digest,
            "forwarded_env_names": list(self.forwarded_env),
            "dependency_scope": "entrypoint only; integrator must pin imported dependencies",
        }

    def execute(self, task: Task, trial: int, seed: int) -> dict[str, Any]:
        spec = task.spec
        environment = Environment(spec["environment"])
        result = empty_observation(task, "error", "Worker did not finish")
        started = time.monotonic()
        stderr = bytearray()
        with tempfile.TemporaryDirectory(prefix="agent-eval-") as directory:
            agent_file = Path(directory) / "agent.py"
            agent_file.write_bytes(self.source)
            child_env = {
                key: os.environ[key]
                for key in ("PATH", "LANG", "LC_ALL", "TZ")
                if key in os.environ
            }
            child_env.update({key: os.environ[key] for key in self.forwarded_env})
            child_env.update({"PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1"})
            initial = {
                "task_id": task.task_id,
                **spec["input"],
                "tools": environment.descriptions(),
                "trial": trial,
                "seed": seed,
                "agent_file": str(agent_file),
                "import_directory": str(self.path.parent),
            }
            process = subprocess.Popen(
                [sys.executable, "-m", "eval_orchestrator.adapters.worker"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=directory,
                env=child_env,
                start_new_session=True,
            )
            assert process.stdin and process.stdout and process.stderr
            stdout_buffer = bytearray()
            pending = bytearray((canonical(initial) + "\n").encode())
            totals = {"stdout": 0, "stderr": 0}
            final_seen = False
            request_id = 0
            selector = selectors.DefaultSelector()
            for stream, label in ((process.stdout, "stdout"), (process.stderr, "stderr")):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, label)
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
            try:
                while True:
                    if time.monotonic() - started > spec["limits"]["timeout_seconds"]:
                        result.update(execution="timeout", error="Wall-clock deadline exceeded")
                        break
                    if not selector.get_map():
                        code = process.poll()
                        if code is not None:
                            if code == 0 and final_seen and not stdout_buffer:
                                result.update(execution="completed", error=None)
                            else:
                                result.update(
                                    execution="error",
                                    error=f"Worker exit {code}; incomplete protocol",
                                )
                            break
                    for key, _ in selector.select(timeout=0.02):
                        if key.data == "stdin":
                            try:
                                written = os.write(key.fd, pending[:65536])
                                del pending[:written]
                            except BrokenPipeError:
                                pending.clear()
                            if not pending:
                                selector.unregister(process.stdin)
                            continue
                        try:
                            chunk = os.read(key.fd, 65536)
                        except BlockingIOError:
                            continue
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        totals[key.data] += len(chunk)
                        if totals[key.data] > MAX_STREAM:
                            raise OverflowError(f"{key.data} exceeded 1 MiB")
                        if key.data == "stderr":
                            stderr.extend(chunk)
                            continue
                        stdout_buffer.extend(chunk)
                        while b"\n" in stdout_buffer:
                            line, _, rest = stdout_buffer.partition(b"\n")
                            stdout_buffer[:] = rest
                            if len(line) > MAX_MESSAGE:
                                raise OverflowError("Protocol message exceeded 256 KiB")
                            message = strict_json(bytes(line))
                            if not isinstance(message, dict) or final_seen:
                                raise ValueError("Unexpected message or data after final output")
                            if message.get("type") == "final":
                                obj(message, {"type", "output"}, set(), "final")
                                json_data(message["output"])
                                result["output"] = message["output"]
                                final_seen = True
                            elif message.get("type") == "tool_call":
                                obj(
                                    message, {"type", "id", "name", "arguments"}, set(), "tool_call"
                                )
                                if (
                                    type(message["id"]) is not int
                                    or message["id"] != request_id + 1
                                ):
                                    raise ValueError("Tool invocation IDs must increase by one")
                                if not isinstance(message["name"], str) or not isinstance(
                                    message["arguments"], dict
                                ):
                                    raise ValueError("Invalid tool invocation")
                                if request_id >= spec["limits"]["max_tool_calls"]:
                                    raise OverflowError("Tool-call limit exceeded")
                                request_id += 1
                                response = environment.call(message["name"], message["arguments"])
                                reply = (
                                    canonical({"id": request_id, "result": response}) + "\n"
                                ).encode()
                                if (
                                    len(reply) > MAX_MESSAGE
                                    or len(canonical(environment.events)) > MAX_TRACE
                                ):
                                    raise OverflowError("Tool response or trace size exceeded")
                                pending.extend(reply)
                                if len(pending) > MAX_STREAM:
                                    raise OverflowError("Pending responses exceeded limit")
                                if process.stdin not in selector.get_map():
                                    try:
                                        selector.get_key(process.stdin)
                                    except KeyError:
                                        selector.register(
                                            process.stdin, selectors.EVENT_WRITE, "stdin"
                                        )
                            else:
                                raise ValueError("Unknown worker protocol message")
                        if len(stdout_buffer) > MAX_MESSAGE:
                            raise OverflowError("Unterminated protocol message exceeded 256 KiB")
            except OverflowError as exc:
                result.update(execution="limit_exceeded", error=str(exc))
            except (ValueError, OSError, KeyError, TypeError) as exc:
                result.update(execution="error", error=f"Worker protocol error: {exc}")
            except KeyboardInterrupt:
                result.update(execution="cancelled", error="Cancelled by operator")
            finally:
                selector.close()
                # Kill the entire process group, including descendants after normal worker exit.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
                process.stdin.close()
                process.stdout.close()
                process.stderr.close()
        result.update(
            events=environment.events,
            final_state=environment.state,
            duration_ms=round((time.monotonic() - started) * 1000, 3),
            tool_calls=len(environment.events),
            stderr=stderr.decode("utf-8", errors="replace"),
        )
        return result
