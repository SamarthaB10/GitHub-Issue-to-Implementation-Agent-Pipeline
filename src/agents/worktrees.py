"""Safe creation of one isolated Git worktree per Runtime worker."""

import re
import subprocess
from pathlib import Path

from schemas.runtime import WorkerAssignment

SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SAFE_TASK_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}(?:/[A-Za-z0-9][A-Za-z0-9._-]{0,63})*$")


class WorktreeError(RuntimeError):
    """Raised when Chief cannot create a safe worker worktree."""


class WorktreeManager:
    """Create worker-owned branches from a validated project commit."""

    def __init__(self, project_workspace: Path | str):
        self.project_workspace = Path(project_workspace).expanduser().resolve()
        self.worktree_root = self.project_workspace / ".chief" / "worktrees"

    def create_assignment(
        self,
        run_id: str,
        task_id: str,
        worker_id: str,
        *,
        base_commit: str,
        assigned_paths: list[str],
        approved_checks: list[list[str]] | None = None,
        required_skills: list[str] | None = None,
        provider: str = "codex",
        timeout_seconds: int = 3_600,
    ) -> WorkerAssignment:
        for value, label, pattern in (
            (run_id, "run_id", SAFE_IDENTIFIER),
            (task_id, "task_id", SAFE_TASK_IDENTIFIER),
            (worker_id, "worker_id", SAFE_IDENTIFIER),
        ):
            if not pattern.fullmatch(value):
                raise WorktreeError(f"{label} contains invalid characters.")
        if provider not in {"codex", "claude"}:
            raise WorktreeError("provider must be codex or claude.")
        self._git(["rev-parse", "--verify", f"{base_commit}^{{commit}}"], "base commit")
        branch = f"chief/{run_id}/{worker_id}"
        worktree_path = self.worktree_root / run_id / worker_id
        if worktree_path.exists():
            raise WorktreeError(f"Worker worktree already exists: {worktree_path}")
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._git(
                ["worktree", "add", "-b", branch, str(worktree_path), base_commit],
                "worker worktree",
            )
        except WorktreeError:
            if worktree_path.exists():
                subprocess.run(
                    ["git", "-C", str(self.project_workspace), "worktree", "remove", "--force", str(worktree_path)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            raise
        return WorkerAssignment(
            run_id=run_id,
            worker_id=worker_id,
            task_id=task_id,
            project_workspace=str(self.project_workspace),
            worktree_path=str(worktree_path),
            branch=branch,
            base_commit=base_commit,
            assigned_paths=assigned_paths,
            approved_checks=approved_checks or [],
            required_skills=required_skills or ["implement", "tdd", "code-review"],
            provider=provider,
            timeout_seconds=timeout_seconds,
        )

    def _git(self, args: list[str], operation: str) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                ["git", "-C", str(self.project_workspace), *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise WorktreeError(f"Git {operation} is unavailable or timed out.") from exc
        if result.returncode != 0:
            raise WorktreeError(f"Git {operation} failed: {result.stderr[:500]}")
        return result
