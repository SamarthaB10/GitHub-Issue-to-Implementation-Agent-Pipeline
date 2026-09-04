from collections import defaultdict
from pathlib import Path

from agents.skill_catalog import SkillCatalog
from agents.state_store import ChiefStateStore
from agents.to_tickets import tasks_from_handoff
from agents.worker_protocol import SkillTraceDecision, SkillTraceGate
from agents.worker_queue import WorkerQueue
from agents.worktrees import WorktreeManager
from schemas.runtime import (
    IntegrationReport,
    PlannerHandoff,
    WorkerAssignment,
    WorkerResult,
    WorkerTask,
)


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

    def accept_planner_handoff(self, handoff: PlannerHandoff) -> list[WorkerTask]:
        """Validate and persist an approved Planner handoff."""

        if Path(handoff.repository_path).expanduser().resolve() != self.project_workspace:
            raise ValueError("Planner handoff repository does not match Chief workspace.")
        existing = self.state_store.get_run(handoff.run_id)
        if existing is None:
            self.start_run(handoff.run_id, base_commit=handoff.base_commit)
        elif existing["base_commit"] != handoff.base_commit:
            raise ValueError("Planner handoff base commit does not match the run.")
        self.state_store.record_handoff(handoff)
        self.state_store.set_run_status(handoff.run_id, "plan_approved")
        return tasks_from_handoff(handoff)

    def create_tasks_from_handoff(self, handoff: PlannerHandoff) -> list[WorkerTask]:
        """Persist Chief tickets created from an approved Planner handoff."""

        tasks = self.accept_planner_handoff(handoff)
        for task in tasks:
            self.state_store.record_task(task)
        self.state_store.set_run_status(handoff.run_id, "delegating")
        return tasks

    def delegate_tasks(
        self,
        handoff: PlannerHandoff,
        *,
        provider: str = "codex",
    ) -> list[WorkerAssignment]:
        """Create isolated assignments and queues for every approved task."""

        tasks = self.create_tasks_from_handoff(handoff)
        manager = WorktreeManager(self.project_workspace)
        assignments = []
        for index, task in enumerate(tasks, start=1):
            worker_id = f"worker-{index}"
            existing = self.state_store.get_worker(worker_id)
            if existing is not None:
                assignments.append(WorkerAssignment.model_validate(existing))
                continue
            assignment = manager.create_assignment(
                handoff.run_id,
                task.task_id,
                worker_id,
                base_commit=handoff.base_commit,
                assigned_paths=task.assigned_paths,
                approved_checks=task.required_checks,
                required_skills=task.required_skills,
                provider=provider,
            )
            self.assign_task(task, assignment, sequence=index)
            assignments.append(assignment)
        return assignments

    def retry_task(
        self,
        task: WorkerTask,
        *,
        worker_id: str,
        sequence: int,
        provider: str = "codex",
    ) -> WorkerAssignment:
        """Retry one task in a fresh worktree and worker branch."""

        run = self.state_store.get_run(task.run_id)
        if run is None:
            raise ValueError(f"Run does not exist: {task.run_id}")
        assignment = WorktreeManager(self.project_workspace).create_assignment(
            task.run_id,
            task.task_id,
            worker_id,
            base_commit=str(run["base_commit"]),
            assigned_paths=task.assigned_paths,
            approved_checks=task.required_checks,
            required_skills=task.required_skills,
            provider=provider,
        )
        self.assign_task(task, assignment, sequence=sequence, priority="error_detection")
        self.state_store.record_event(
            task.run_id,
            "worker_retry_created",
            {"worker_id": worker_id, "task_id": task.task_id},
        )
        return assignment

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
        worker_context_dir = (
            Path(assignment.worktree_path) / ".chief-worker" / "context"
        )
        self.prepare_worker_context(assignment, worker_context_dir)
        self.state_store.record_event(
            assignment.run_id,
            "subagent_context_prepared",
            {
                "worker_id": assignment.worker_id,
                "rules_file": str(context_dir / "sub_agents.md"),
                "context_file": str(context_dir / "context.agent"),
                "worker_rules_file": str(worker_context_dir / "sub_agents.md"),
                "worker_context_file": str(worker_context_dir / "context.agent"),
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

        assignment_raw = self.state_store.get_worker(result.worker_id)
        assignment = (
            WorkerAssignment.model_validate(assignment_raw)
            if assignment_raw is not None
            else None
        )
        decision = (
            self.skill_gate.check(result, assignment)
            if assignment is not None
            else SkillTraceDecision(
                accepted=False,
                missing_phases=[],
                violations=["WorkerResult has no recorded assignment."],
            )
        )
        self.state_store.record_worker_result(result)
        if decision.accepted:
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

    def integration_report(self, run_id: str) -> IntegrationReport:
        """Build a report for human-led branch integration without merging."""

        results = self.state_store.worker_results_for_run(run_id)
        file_workers: dict[str, list[str]] = defaultdict(list)
        commits: dict[str, str] = {}
        changed_files: dict[str, list[str]] = {}
        errors: list[str] = []
        accepted_workers: list[str] = []
        for raw in results:
            result = WorkerResult.model_validate(raw)
            decision = self.skill_gate.check(result)
            if result.status == "completed" and decision.accepted:
                accepted_workers.append(result.worker_id)
            changed_files[result.worker_id] = result.changed_files
            if result.commit:
                commits[result.worker_id] = result.commit
            for path in result.changed_files:
                file_workers[path].append(result.worker_id)
            errors.extend(result.errors)
            errors.extend(decision.missing_phases)
            errors.extend(decision.violations)
        overlapping = sorted(
            path for path, workers in file_workers.items() if len(workers) > 1
        )
        blocked = not accepted_workers or bool(overlapping) or bool(errors)
        if blocked:
            next_action = (
                "Resolve worker errors and overlapping files before human integration."
                if accepted_workers
                else "Wait for an accepted WorkerResult before human integration."
            )
        else:
            next_action = "Review worker commits and integrate selected branches into main."
        return IntegrationReport(
            run_id=run_id,
            status="blocked" if blocked else "ready_for_human",
            accepted_workers=accepted_workers,
            worker_commits=commits,
            changed_files=changed_files,
            overlapping_files=overlapping,
            errors=errors,
            next_action=next_action,
        )
