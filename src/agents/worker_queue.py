from pathlib import Path

from agents.state_store import ChiefStateStore
from schemas.runtime import QueueEntry, WorkerTask


class WorkerQueue:
    """Append Chief tickets to the authoritative and worker-local queues."""

    def __init__(
        self,
        project_workspace: Path | str,
        worktree: Path | str,
        worker_id: str,
        state_store: ChiefStateStore | None = None,
    ):
        self.project_workspace = Path(project_workspace).expanduser().resolve()
        self.worktree = Path(worktree).expanduser().resolve()
        self.worker_id = worker_id
        self.state_store = state_store
        self.authoritative_path = (
            self.project_workspace
            / ".chief"
            / "workers"
            / worker_id
            / "sub_agent_queue.md"
        )
        self.worker_path = self.worktree / ".chief-worker" / "sub_agent_queue.md"

    def enqueue(self, task: WorkerTask, *, sequence: int, priority: str = "workflow"):
        entry = QueueEntry(
            queue_id=f"{task.run_id}/{self.worker_id}/{sequence}",
            run_id=task.run_id,
            worker_id=self.worker_id,
            sequence=sequence,
            priority=priority,
            kind="task",
            task_id=task.task_id,
            title=task.title,
            description=task.description,
            blocked_by=task.blocked_by,
            acceptance_criteria=task.acceptance_criteria,
            assigned_paths=task.assigned_paths,
            required_checks=task.required_checks,
            required_skills=task.required_skills,
        )
        self.append(entry)
        return entry

    def append(self, entry: QueueEntry) -> None:
        if entry.worker_id != self.worker_id:
            raise ValueError("Queue entry belongs to a different worker.")
        if self._contains_queue_id(entry.queue_id):
            raise ValueError(f"Queue entry already exists: {entry.queue_id}")

        rendered = self._render(entry)
        for path in (self.authoritative_path, self.worker_path):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as queue_file:
                queue_file.write(rendered)
        if self.state_store is not None:
            self.state_store.record_queue_entry(entry)

    def _contains_queue_id(self, queue_id: str) -> bool:
        return any(
            f"## {queue_id}:" in path.read_text(encoding="utf-8")
            for path in (self.authoritative_path, self.worker_path)
            if path.is_file()
        )

    @staticmethod
    def _render(entry: QueueEntry) -> str:
        blocked_by = ", ".join(entry.blocked_by) or "None"
        criteria = "\n".join(
            f"- [ ] {criterion}" for criterion in entry.acceptance_criteria
        ) or "- [ ] No acceptance criteria supplied"
        checks = "\n".join(
            f"- `{check}`" for check in entry.required_checks
        ) or "- None"
        skills = ", ".join(entry.required_skills) or "None"
        supersedes = entry.supersedes_entry_id or "None"
        return f"""\n## {entry.queue_id}: {entry.title}

- Kind: `{entry.kind}`
- Priority: `{entry.priority}`
- Task: `{entry.task_id}`
- Blocked by: {blocked_by}
- Supersedes: {supersedes}
- Required skills: `{skills}`

### What to build

{entry.description}

### Assigned paths

{chr(10).join(f"- `{path}`" for path in entry.assigned_paths) or "- None"}

### Required checks

{checks}

### Acceptance criteria

{criteria}
"""
