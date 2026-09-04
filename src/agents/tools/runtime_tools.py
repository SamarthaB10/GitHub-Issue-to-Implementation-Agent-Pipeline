import hashlib
import os
import re
import selectors
import signal
import subprocess
import threading
import time
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field

from agents.tools.python_tools import build_python_tools
from agents.tools.repository_tools import (
    MAX_COMMAND_OUTPUT,
    build_repository_tools,
)
from schemas.runtime import (
    CheckResult,
    GitResult,
    PatchResult,
    SkillTrace,
    WorkerAssignment,
)

MAX_PATCH_BYTES = 256_000
MAX_PATCH_FILES = 20
MAX_CHANGED_LINES = 2_000
MAX_CHECK_TIMEOUT = 600
MAX_PROCESS_OUTPUT = 12_000
MAX_COMMIT_MESSAGE = 500


class RuntimeToolViolation(ValueError):
    """Raised when a Runtime worker requests an unsafe operation."""


class AuditEvent(BaseModel):
    """An in-memory audit event emitted by a Runtime tool call."""

    model_config = ConfigDict(extra="forbid")

    event_type: str
    status: str
    worker_id: str
    details: dict[str, object] = Field(default_factory=dict)


def _bounded_text(value: str, limit: int = MAX_PROCESS_OUTPUT) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n... output truncated ..."


class WorktreeGuard:
    """Verify a Runtime worker's Worktree, branch, and assigned scope."""

    def __init__(self, assignment: WorkerAssignment):
        self.assignment = assignment
        self.worktree = Path(assignment.worktree_path).expanduser()
        self.project_workspace = Path(assignment.project_workspace).expanduser()

    def verify_ownership(self) -> Path:
        if self.worktree.is_symlink():
            raise RuntimeToolViolation("Assigned Worktree cannot be a symlink.")

        try:
            worktree = self.worktree.resolve(strict=True)
            project_workspace = self.project_workspace.resolve(strict=True)
        except OSError as exc:
            raise RuntimeToolViolation(f"Worktree path cannot be resolved: {exc}") from exc

        if not worktree.is_dir():
            raise RuntimeToolViolation("Assigned Worktree is not a directory.")
        if worktree == project_workspace:
            raise RuntimeToolViolation(
                "The Chief project workspace cannot be a Runtime Worktree."
            )

        top_level = self._git(["rev-parse", "--show-toplevel"])
        if top_level.returncode != 0:
            raise RuntimeToolViolation("Assigned path is not a Git Worktree.")
        if Path(top_level.stdout.strip()).resolve() != worktree:
            raise RuntimeToolViolation("Git Worktree ownership does not match.")

        branch_result = self._git(["branch", "--show-current"])
        branch = branch_result.stdout.strip()
        if branch_result.returncode != 0 or not branch:
            raise RuntimeToolViolation("Runtime worker must use a named branch.")
        if branch != self.assignment.branch:
            raise RuntimeToolViolation(
                f"Worker branch mismatch: expected {self.assignment.branch}, got {branch}."
            )
        if branch in set(self.assignment.protected_branches):
            raise RuntimeToolViolation(f"Cannot operate on protected branch: {branch}.")

        worktrees = self._git(["worktree", "list", "--porcelain"])
        if worktrees.returncode != 0 or not self._worktree_is_registered(
            worktrees.stdout, worktree, branch
        ):
            raise RuntimeToolViolation("Assigned Worktree is not registered for its branch.")

        return worktree

    def path_for(self, relative_path: str, *, require_existing: bool = False) -> Path:
        worktree = self.verify_ownership()
        relative = self._normalise_relative_path(relative_path)

        if not self.path_is_assigned(relative):
            raise RuntimeToolViolation(
                f"Path is outside assigned scope: {relative}"
            )

        candidate = worktree / relative
        current = worktree
        for part in PurePosixPath(relative).parts:
            current = current / part
            if current.is_symlink():
                raise RuntimeToolViolation("Symlink paths are not allowed.")

        try:
            resolved = candidate.resolve(strict=require_existing)
            resolved.relative_to(worktree)
        except (OSError, ValueError) as exc:
            raise RuntimeToolViolation("Path escapes the assigned Worktree.") from exc

        return resolved

    def path_is_assigned(self, relative_path: str) -> bool:
        candidate = PurePosixPath(relative_path)
        for pattern in self.assignment.assigned_paths:
            normalised_pattern = self._normalise_relative_path(pattern)
            if (
                candidate == PurePosixPath(normalised_pattern)
                or candidate.match(normalised_pattern)
                or normalised_pattern.endswith("/**")
                and candidate.is_relative_to(
                    PurePosixPath(normalised_pattern[:-3].rstrip("/"))
                )
            ):
                return True
        return False

    @staticmethod
    def _normalise_relative_path(relative_path: str) -> str:
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise RuntimeToolViolation("A relative path is required.")
        if "\\" in relative_path or "\x00" in relative_path:
            raise RuntimeToolViolation("Invalid path characters.")

        path = PurePosixPath(relative_path.strip())
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeToolViolation("Absolute paths and path escapes are not allowed.")
        if any(part in {".git", ".chief", ".chief-worker"} for part in path.parts):
            raise RuntimeToolViolation("Control paths are not allowed.")
        return path.as_posix()

    def _git(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", "-C", str(self.worktree), *args],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise RuntimeToolViolation("Git is unavailable or timed out.") from exc

    @staticmethod
    def _worktree_is_registered(
        output: str,
        worktree: Path,
        branch: str,
    ) -> bool:
        records = output.split("\n\n")
        expected_branch = f"refs/heads/{branch}"
        for record in records:
            lines = dict(
                line.split(" ", 1)
                for line in record.splitlines()
                if " " in line
            )
            if (
                Path(lines.get("worktree", "")).resolve() == worktree
                and lines.get("branch") == expected_branch
            ):
                return True
        return False


class RuntimeToolService:
    """Provide guarded edit, check, and Git tools to one Runtime worker."""

    _edit_lock = threading.Lock()

    def __init__(self, assignment: WorkerAssignment):
        self.assignment = assignment
        self.guard = WorktreeGuard(assignment)
        self.audit_events: list[AuditEvent] = []
        self.skill_traces: list[SkillTrace] = []

    def record_skill_trace(
        self,
        *,
        skill: str,
        phase: str,
        status: str = "completed",
        evidence: dict[str, object] | None = None,
    ) -> SkillTrace:
        """Record one observable phase in the Runtime worker pipeline."""

        self.guard.verify_ownership()
        if not isinstance(skill, str) or not skill.strip():
            raise RuntimeToolViolation("Skill name cannot be empty.")
        if skill not in self.assignment.required_skills:
            raise RuntimeToolViolation(
                f"Skill is not in the assigned route: {skill}"
            )
        try:
            trace = SkillTrace(
                sequence=len(self.skill_traces) + 1,
                skill=skill,
                phase=phase,
                status=status,
                evidence=evidence or {},
            )
        except ValueError as exc:
            raise RuntimeToolViolation(f"Invalid Skill trace: {exc}") from exc
        self.skill_traces.append(trace)
        self._record(
            "skill_trace",
            status,
            {"skill": skill, "phase": phase, "sequence": trace.sequence},
        )
        return trace

    def apply_file_patch(
        self,
        *,
        patch: str,
        expected_files: dict[str, str | None],
    ) -> PatchResult:
        self.guard.verify_ownership()
        if not patch.strip():
            raise RuntimeToolViolation("Patch cannot be empty.")
        if len(patch.encode("utf-8")) > MAX_PATCH_BYTES:
            raise RuntimeToolViolation("Patch is too large.")

        changed_files = self._patch_paths(patch)
        if len(changed_files) > MAX_PATCH_FILES:
            raise RuntimeToolViolation("Patch changes too many files.")
        if self._changed_line_count(patch) > MAX_CHANGED_LINES:
            raise RuntimeToolViolation("Patch changes too many lines.")
        if set(expected_files) != set(changed_files):
            raise RuntimeToolViolation(
                "Expected file hashes must list exactly every changed file."
            )

        with self._edit_lock:
            for relative_path in changed_files:
                file_path = self.guard.path_for(relative_path)
                expected_hash = expected_files[relative_path]
                exists = file_path.exists()
                if expected_hash is None:
                    if exists:
                        raise RuntimeToolViolation(
                            f"Expected new file is already present: {relative_path}"
                        )
                elif not exists:
                    raise RuntimeToolViolation(
                        f"Expected file does not exist: {relative_path}"
                    )
                elif self._sha256(file_path) != expected_hash:
                    raise RuntimeToolViolation(
                        f"File hash does not match: {relative_path}"
                    )

            check = self._apply_git_patch(patch, check_only=True)
            if check.returncode != 0:
                raise RuntimeToolViolation(
                    f"Patch rejected: {_bounded_text(check.stderr, 2_000)}"
                )
            applied = self._apply_git_patch(patch, check_only=False)
            if applied.returncode != 0:
                raise RuntimeToolViolation(
                    f"Patch application failed: {_bounded_text(applied.stderr, 2_000)}"
                )

        self._record("file_patch", "applied", {"files": changed_files})
        return PatchResult(status="applied", changed_files=changed_files)

    def run_check(self, argv: list[str], timeout_seconds: int = 120) -> CheckResult:
        self.guard.verify_ownership()
        if not argv or any(not isinstance(value, str) or not value for value in argv):
            raise RuntimeToolViolation("A non-empty command argument list is required.")
        if list(argv) not in self.assignment.approved_checks:
            raise RuntimeToolViolation("Check command is not approved for this task.")
        if not 1 <= timeout_seconds <= MAX_CHECK_TIMEOUT:
            raise RuntimeToolViolation(
                f"Check timeout must be between 1 and {MAX_CHECK_TIMEOUT} seconds."
            )

        try:
            process = subprocess.Popen(
                argv,
                cwd=self.guard.worktree,
                env=self._safe_environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                text=False,
            )
        except OSError as exc:
            raise RuntimeToolViolation(f"Check could not start: {exc}") from exc

        stdout, stderr, timed_out = self._collect_process_output(
            process,
            timeout_seconds,
        )
        exit_code = process.returncode
        status = "timed_out" if timed_out else "passed" if exit_code == 0 else "failed"
        result = CheckResult(
            status=status,
            argv=list(argv),
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
        )
        self._record("check", status, {"argv": argv, "exit_code": exit_code})
        return result

    def git_status(self) -> GitResult:
        self.guard.verify_ownership()
        result = self._git(["status", "--short"])
        if result.returncode != 0:
            raise RuntimeToolViolation(f"Git status failed: {_bounded_text(result.stderr)}")
        branch = self._branch()
        output = _bounded_text(result.stdout)
        return GitResult(
            status="clean" if not output.strip() else "changes",
            branch=branch,
            output=output,
        )

    def git_diff(self) -> str:
        self.guard.verify_ownership()
        result = self._git(["diff", "--no-ext-diff", "--"])
        if result.returncode != 0:
            raise RuntimeToolViolation(f"Git diff failed: {_bounded_text(result.stderr)}")
        return _bounded_text(result.stdout, MAX_COMMAND_OUTPUT)

    def git_commit(self, message: str) -> GitResult:
        self.guard.verify_ownership()
        if not isinstance(message, str) or not message.strip():
            raise RuntimeToolViolation("Commit message cannot be empty.")
        if len(message) > MAX_COMMIT_MESSAGE or "\x00" in message:
            raise RuntimeToolViolation("Commit message is invalid or too long.")

        status = self._git(["status", "--porcelain=v1", "--untracked-files=all"])
        if status.returncode != 0:
            raise RuntimeToolViolation(f"Git status failed: {_bounded_text(status.stderr)}")
        changed_files = self._status_paths(status.stdout)
        for relative_path in changed_files:
            self.guard.path_for(relative_path)

        if not changed_files:
            return GitResult(status="no_changes", branch=self._branch())

        added = self._git(["add", "--all", "--", "."])
        if added.returncode != 0:
            raise RuntimeToolViolation(f"Git add failed: {_bounded_text(added.stderr)}")
        committed = self._git(["commit", "-m", message])
        if committed.returncode != 0:
            raise RuntimeToolViolation(
                f"Git commit failed: {_bounded_text(committed.stderr)}"
            )
        revision = self._git(["rev-parse", "HEAD"])
        commit = revision.stdout.strip() if revision.returncode == 0 else None
        self._record("git_commit", "committed", {"commit": commit})
        return GitResult(
            status="committed",
            branch=self._branch(),
            output=_bounded_text(committed.stdout),
            commit=commit,
        )

    def _apply_git_patch(
        self,
        patch: str,
        *,
        check_only: bool,
    ) -> subprocess.CompletedProcess[str]:
        args = ["git", "-C", str(self.guard.worktree), "apply"]
        if check_only:
            args.append("--check")
        args.extend(["--whitespace=nowarn", "-"])
        return subprocess.run(
            args,
            input=patch,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    @staticmethod
    def _patch_paths(patch: str) -> list[str]:
        paths: list[str] = []
        for line in patch.splitlines():
            if line.startswith(("Binary files ", "GIT binary patch")):
                raise RuntimeToolViolation("Binary patches are not supported.")
            if line.startswith(("old mode ", "new mode ")):
                raise RuntimeToolViolation("Permission changes are not supported.")
            if line.startswith("new file mode ") and line != "new file mode 100644":
                raise RuntimeToolViolation("Only regular file patches are supported.")
            if line.startswith("diff --git "):
                match = re.fullmatch(r"diff --git a/(.+) b/(.+)", line)
                if not match:
                    raise RuntimeToolViolation("Patch file headers are invalid.")
                for path in match.groups():
                    if path not in paths:
                        paths.append(path)
        if not paths:
            raise RuntimeToolViolation("Patch has no file headers.")
        return paths

    @staticmethod
    def _changed_line_count(patch: str) -> int:
        return sum(
            line.startswith(("+", "-"))
            and not line.startswith(("+++", "---"))
            for line in patch.splitlines()
        )

    @staticmethod
    def _sha256(file_path: Path) -> str:
        return hashlib.sha256(file_path.read_bytes()).hexdigest()

    def _safe_environment(self) -> dict[str, str]:
        environment = {}
        for key in ("PATH", "LANG", "LC_ALL", "TMPDIR"):
            value = os.environ.get(key)
            if value:
                environment[key] = value
        environment["CHIEF_RUN_ID"] = self.assignment.run_id
        environment["CHIEF_WORKER_ID"] = self.assignment.worker_id
        environment["CHIEF_TASK_ID"] = self.assignment.task_id
        return environment

    @staticmethod
    def _collect_process_output(
        process: subprocess.Popen,
        timeout_seconds: int,
    ) -> tuple[str, str, bool]:
        selector = selectors.DefaultSelector()
        assert process.stdout is not None
        assert process.stderr is not None
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        streams = {"stdout": bytearray(), "stderr": bytearray()}
        deadline = time.monotonic() + timeout_seconds
        timed_out = False

        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                RuntimeToolService._terminate_process(process)
                break
            for key, _ in selector.select(min(remaining, 0.1)):
                chunk = os.read(key.fileobj.fileno(), 8_192)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                stream = streams[key.data]
                if len(stream) < MAX_PROCESS_OUTPUT:
                    stream.extend(chunk[: MAX_PROCESS_OUTPUT - len(stream)])

        if timed_out:
            process.wait(timeout=5)
        else:
            process.wait(timeout=5)
        selector.close()
        return (
            _bounded_text(bytes(streams["stdout"]).decode("utf-8", errors="replace")),
            _bounded_text(bytes(streams["stderr"]).decode("utf-8", errors="replace")),
            timed_out,
        )

    @staticmethod
    def _terminate_process(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass

    def _branch(self) -> str:
        result = self.guard._git(["branch", "--show-current"])
        return result.stdout.strip()

    @staticmethod
    def _status_paths(output: str) -> list[str]:
        paths = []
        for line in output.splitlines():
            if len(line) < 4:
                continue
            path = line[3:]
            if " -> " in path:
                source, target = path.split(" -> ", 1)
                paths.extend([source, target])
            else:
                paths.append(path)
        return paths

    def _git(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", "-C", str(self.guard.worktree), *args],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise RuntimeToolViolation("Git is unavailable or timed out.") from exc

    def _record(self, event_type: str, status: str, details: dict[str, object]) -> None:
        self.audit_events.append(
            AuditEvent(
                event_type=event_type,
                status=status,
                worker_id=self.assignment.worker_id,
                details=details,
            )
        )


def build_runtime_worker_tools(assignment: WorkerAssignment):
    """Build repository, edit, check, and Git tools for one Runtime worker."""

    service = RuntimeToolService(assignment)

    from langchain.tools import tool

    @tool
    def apply_file_patch(
        patch: str,
        expected_files: dict[str, str | None],
    ) -> str:
        """Apply one hash-checked patch inside the assigned Worktree."""

        return service.apply_file_patch(
            patch=patch,
            expected_files=expected_files,
        ).model_dump_json()

    @tool
    def run_check(argv: list[str], timeout_seconds: int = 120) -> str:
        """Run one exact approved check in the assigned Worktree."""

        return service.run_check(argv, timeout_seconds).model_dump_json()

    @tool
    def git_status() -> str:
        """Inspect the assigned Worktree status."""

        return service.git_status().model_dump_json()

    @tool
    def git_diff() -> str:
        """Inspect the assigned Worktree diff."""

        return service.git_diff()

    @tool
    def git_commit(message: str) -> str:
        """Commit assigned-scope changes on the owned Worker branch."""

        return service.git_commit(message).model_dump_json()

    @tool
    def record_skill_trace(
        skill: str,
        phase: str,
        status: str = "completed",
        evidence: dict[str, object] | None = None,
    ) -> str:
        """Record evidence for one required Runtime worker skill phase."""

        return service.record_skill_trace(
            skill=skill,
            phase=phase,
            status=status,
            evidence=evidence,
        ).model_dump_json()

    return [
        *build_repository_tools(assignment.worktree_path),
        *build_python_tools(assignment.worktree_path),
        apply_file_patch,
        run_check,
        git_status,
        git_diff,
        git_commit,
        record_skill_trace,
    ]
