from pathlib import Path

from agents.skill_catalog import SkillCatalog
from agents.state_store import ChiefStateStore
from agents.worker_protocol import SkillTraceDecision, SkillTraceGate
from agents.worker_queue import WorkerQueue
from schemas.runtime import WorkerAssignment, WorkerResult, WorkerTask


class ChiefCoordinator:
    """Coordinate Chief's ticket and WorkerResult boundaries."""

    def __init__(
        self,
        project_workspace: Path | str,
        *,
        skill_catalog: SkillCatalog | None = None,
    ):
        self.project_workspace = Path(project_workspace).expanduser().resolve()
        self.state_store = ChiefStateStore(self.project_workspace)
        self.state_store.initialize()
        self.skill_catalog = skill_catalog
        self.skill_gate = SkillTraceGate()

    def start_run(self, run_id: str, *, base_commit: str) -> None:
        """Create the durable run record before Chief delegates tickets."""

        self.state_store.create_run(run_id, base_commit=base_commit)

    def assign_task(
        self,
        task: WorkerTask,
        assignment: WorkerAssignment,
        *,
        sequence: int,
        priority: str = "workflow",
    ):
        """Record and queue one ticket for one Runtime worker."""

        if task.run_id != assignment.run_id:
            raise ValueError("Task and assignment must belong to the same run.")
        if task.task_id != assignment.task_id:
            raise ValueError("Task and assignment must refer to the same task.")
        context_dir = (
            self.project_workspace
            / ".chief"
            / "workers"
            / assignment.worker_id
            / "context"
        )
        self.prepare_worker_context(assignment, context_dir)
        self.state_store.record_event(
            assignment.run_id,
            "subagent_context_prepared",
            {
                "worker_id": assignment.worker_id,
                "rules_file": str(context_dir / "sub_agents.md"),
                "context_file": str(context_dir / "context.agent"),
            },
        )
        self.state_store.record_task(task)
        self.state_store.record_worker(assignment)
        queue = WorkerQueue(
            self.project_workspace,
            assignment.worktree_path,
            assignment.worker_id,
            self.state_store,
        )
        return queue.enqueue(task, sequence=sequence, priority=priority)

    def prepare_worker_context(self, assignment: WorkerAssignment, output_dir: Path | str):
        """Prepare both context files before Chief opens a Runtime worker."""

        if self.skill_catalog is None:
            self.skill_catalog = SkillCatalog.from_project(self.project_workspace)
        return self.skill_catalog.prepare_subagent_context(assignment, output_dir)

    def accept_worker_result(self, result: WorkerResult) -> SkillTraceDecision:
        """Gate and persist a WorkerResult after Chief inspects its traces."""

        decision = self.skill_gate.check(result)
        if decision.accepted:
            self.state_store.record_worker_result(result)
            self.state_store.record_event(
                result.run_id,
                "worker_result_accepted",
                {"worker_id": result.worker_id, "task_id": result.task_id},
            )
        else:
            self.state_store.record_event(
                result.run_id,
                "worker_result_rejected",
                {
                    "worker_id": result.worker_id,
                    "task_id": result.task_id,
                    "missing_phases": decision.missing_phases,
                    "violations": decision.violations,
                },
            )
        return decision
