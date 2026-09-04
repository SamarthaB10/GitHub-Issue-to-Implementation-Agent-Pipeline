"""Chief supervision of provider processes and WorkerResult evidence."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from agents.chief import ChiefCoordinator
from agents.providers import (
    ProviderAdapter,
    SubprocessWorkerProcess,
    WorkerExecution,
    WorkerLaunch,
    WorkerProcess,
)
from agents.worker_protocol import SkillTraceDecision
from schemas.runtime import WorkerAssignment, WorkerResult


@dataclass(frozen=True)
class WorkerLifecycleOutcome:
    execution: WorkerExecution
    result: WorkerResult
    decision: SkillTraceDecision

    @property
    def accepted(self) -> bool:
        return self.decision.accepted


class WorkerLifecycleManager:
    """Start, inspect, stop, and accept one worker process at a time."""

    def __init__(
        self,
        chief: ChiefCoordinator,
        *,
        process_factory: Callable[[WorkerAssignment, WorkerLaunch, Path], WorkerProcess]
        | None = None,
    ):
        self.chief = chief
        self._process_factory = process_factory or self._default_process
        self._active: dict[str, tuple[WorkerAssignment, WorkerProcess, Path]] = {}

    def start(self, assignment: WorkerAssignment, provider: ProviderAdapter) -> None:
        if assignment.worker_id in self._active:
            raise ValueError(f"Worker is already active: {assignment.worker_id}")
        if provider.name != assignment.provider:
            raise ValueError("Provider does not match the worker assignment.")
        launch = provider.build_launch(assignment)
        result_path = Path(assignment.worktree_path) / ".chief-worker" / "result.json"
        process = self._process_factory(assignment, launch, result_path)
        process.start()
        self._active[assignment.worker_id] = (assignment, process, result_path)
        if self.chief.state_store.get_worker(assignment.worker_id) is None:
            self.chief.state_store.record_worker(assignment)
        self.chief.state_store.record_event(
            assignment.run_id,
            "worker_started",
            {"worker_id": assignment.worker_id, "provider": provider.name},
        )

    def poll(self, worker_id: str) -> WorkerExecution | None:
        return self._active_entry(worker_id)[1].poll()

    def stop(self, worker_id: str) -> None:
        assignment, process, _ = self._active_entry(worker_id)
        process.stop()
        self.chief.state_store.record_event(
            assignment.run_id,
            "worker_stop_requested",
            {"worker_id": worker_id},
        )

    def wait(self, worker_id: str, *, timeout_seconds: int | None = None) -> WorkerLifecycleOutcome:
        assignment, process, result_path = self._active_entry(worker_id)
        execution = process.wait(timeout_seconds or assignment.timeout_seconds)
        result = self._read_result(assignment, result_path, execution)
        decision = self.chief.accept_worker_result(result)
        self._active.pop(worker_id, None)
        self.chief.state_store.record_event(
            assignment.run_id,
            "worker_finished",
            {
                "worker_id": worker_id,
                "status": execution.status,
                "accepted": decision.accepted,
            },
        )
        return WorkerLifecycleOutcome(execution, result, decision)

    def recoverable_assignments(self, run_id: str) -> list[WorkerAssignment]:
        """Find persisted assignments that have no recorded result yet."""

        completed = {
            (result["worker_id"], result["task_id"])
            for result in self.chief.state_store.worker_results_for_run(run_id)
        }
        assignments = []
        for raw in self.chief.state_store.workers_for_run(run_id):
            assignment = WorkerAssignment.model_validate(raw)
            if (assignment.worker_id, assignment.task_id) not in completed:
                assignments.append(assignment)
        return assignments

    def _active_entry(self, worker_id: str):
        try:
            return self._active[worker_id]
        except KeyError as exc:
            raise KeyError(f"Worker is not active: {worker_id}") from exc

    @staticmethod
    def _default_process(assignment: WorkerAssignment, launch: WorkerLaunch, result_path: Path):
        return SubprocessWorkerProcess(
            assignment,
            launch.argv,
            result_path=result_path,
            context_dir=Path(assignment.worktree_path) / ".chief-worker" / "context",
        )

    @staticmethod
    def _read_result(
        assignment: WorkerAssignment,
        result_path: Path,
        execution: WorkerExecution,
    ) -> WorkerResult:
        if result_path.is_file():
            try:
                result = WorkerResult.model_validate_json(
                    result_path.read_text(encoding="utf-8")
                )
                if execution.status == "completed":
                    return result
                return result.model_copy(
                    update={
                        "status": "failed",
                        "errors": [
                            *result.errors,
                            f"Worker process ended with status {execution.status}.",
                        ],
                    }
                )
            except (OSError, ValueError) as exc:
                error = f"WorkerResult could not be validated: {exc}"
        else:
            error = "Worker did not write a WorkerResult file."
        if execution.status == "timed_out":
            error = f"Worker timed out. {error}"
        elif execution.status == "failed":
            error = f"Worker process failed. {error}"
        return WorkerResult(
            run_id=assignment.run_id,
            worker_id=assignment.worker_id,
            task_id=assignment.task_id,
            status="failed",
            errors=[error],
        )
