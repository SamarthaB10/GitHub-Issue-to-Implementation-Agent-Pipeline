"""Provider-neutral process launch contracts for Codex and Claude workers."""

import os
import shlex
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from schemas.runtime import WorkerAssignment

MAX_WORKER_OUTPUT = 12_000


@dataclass(frozen=True)
class WorkerLaunch:
    """The safe process inputs produced by a provider adapter."""

    argv: tuple[str, ...]
    prompt: str
    environment: dict[str, str]


@dataclass(frozen=True)
class WorkerExecution:
    """A bounded process outcome."""

    status: str
    exit_code: int | None
    stdout: str
    stderr: str


class ProviderAdapter(Protocol):
    name: str

    def build_launch(self, assignment: WorkerAssignment) -> WorkerLaunch:
        ...


def _safe_environment(assignment: WorkerAssignment, context_dir: Path, result_path: Path) -> dict[str, str]:
    environment = {
        key: os.environ[key]
        for key in ("PATH", "LANG", "LC_ALL", "TMPDIR")
        if os.environ.get(key)
    }
    environment.update(
        {
            "CHIEF_RUN_ID": assignment.run_id,
            "CHIEF_WORKER_ID": assignment.worker_id,
            "CHIEF_TASK_ID": assignment.task_id,
            "CHIEF_CONTEXT_DIR": str(context_dir),
            "CHIEF_RESULT_PATH": str(result_path),
        }
    )
    return environment


class CommandProvider:
    """Adapt any approved CLI command to the common worker contract."""

    def __init__(self, name: str, command: tuple[str, ...]):
        if not name or not command or any(not part for part in command):
            raise ValueError("A provider needs a name and a non-empty command.")
        self.name = name
        self.command = command

    @classmethod
    def from_environment(cls, name: str) -> "CommandProvider":
        variable = f"CHIEF_{name.upper()}_COMMAND"
        configured = os.getenv(variable)
        if configured:
            command = tuple(shlex.split(configured))
        elif name == "codex":
            command = ("codex", "exec")
        elif name == "claude":
            command = ("claude", "-p")
        else:
            raise ValueError(f"Unknown worker provider: {name}")
        return cls(name, command)

    def build_launch(self, assignment: WorkerAssignment) -> WorkerLaunch:
        prompt = (
            "Read .chief-worker/context/context.agent and "
            ".chief-worker/context/sub_agents.md. Execute the assigned task "
            "from .chief-worker/sub_agent_queue.md. Follow the required Skill "
            "pipeline and write the final WorkerResult JSON to "
            "$CHIEF_RESULT_PATH."
        )
        context_dir = Path(assignment.worktree_path) / ".chief-worker" / "context"
        result_path = Path(assignment.worktree_path) / ".chief-worker" / "result.json"
        return WorkerLaunch(
            argv=(*self.command, prompt),
            prompt=prompt,
            environment=_safe_environment(assignment, context_dir, result_path),
        )


class WorkerProcess(Protocol):
    def start(self) -> None:
        ...

    def poll(self) -> WorkerExecution | None:
        ...

    def wait(self, timeout_seconds: int) -> WorkerExecution:
        ...

    def stop(self) -> None:
        ...


class SubprocessWorkerProcess:
    """Run one provider CLI with no shell and a sanitized environment."""

    def __init__(
        self,
        assignment: WorkerAssignment,
        argv: tuple[str, ...],
        *,
        result_path: Path,
        context_dir: Path,
    ):
        self.assignment = assignment
        self.argv = argv
        self.result_path = result_path
        self.context_dir = context_dir
        self._process: subprocess.Popen | None = None
        self._stdout_file = None
        self._stderr_file = None

    def start(self) -> None:
        self.context_dir.mkdir(parents=True, exist_ok=True)
        self.result_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path = self.result_path.with_suffix(".stdout.log")
        stderr_path = self.result_path.with_suffix(".stderr.log")
        self._stdout_file = stdout_path.open("w", encoding="utf-8")
        self._stderr_file = stderr_path.open("w", encoding="utf-8")
        try:
            self._process = subprocess.Popen(
                list(self.argv),
                cwd=self.assignment.worktree_path,
                env=_safe_environment(self.assignment, self.context_dir, self.result_path),
                stdin=subprocess.DEVNULL,
                stdout=self._stdout_file,
                stderr=self._stderr_file,
                start_new_session=True,
                text=True,
            )
        except OSError:
            self._close_logs()
            raise

    def poll(self) -> WorkerExecution | None:
        if self._process is None:
            raise RuntimeError("Worker process has not started.")
        if self._process.poll() is None:
            return None
        return self._finish("completed" if self._process.returncode == 0 else "failed")

    def wait(self, timeout_seconds: int) -> WorkerExecution:
        if self._process is None:
            raise RuntimeError("Worker process has not started.")
        try:
            self._process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            self.stop()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
            return self._finish("timed_out")
        return self._finish("completed" if self._process.returncode == 0 else "failed")

    def stop(self) -> None:
        if self._process is None or self._process.poll() is not None:
            return
        if os.name == "posix":
            os.killpg(self._process.pid, signal.SIGTERM)
        else:
            self._process.terminate()

    def _finish(self, status: str) -> WorkerExecution:
        assert self._process is not None
        self._close_logs()
        return WorkerExecution(
            status=status,
            exit_code=self._process.returncode,
            stdout=self._read_log(self.result_path.with_suffix(".stdout.log")),
            stderr=self._read_log(self.result_path.with_suffix(".stderr.log")),
        )

    def _close_logs(self) -> None:
        for stream in (self._stdout_file, self._stderr_file):
            if stream is not None and not stream.closed:
                stream.close()

    @staticmethod
    def _read_log(path: Path) -> str:
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")[:MAX_WORKER_OUTPUT]
