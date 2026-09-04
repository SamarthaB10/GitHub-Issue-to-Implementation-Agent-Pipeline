from pathlib import Path

from agents.chief import ChiefCoordinator
from schemas.runtime import (
    IntegrationReport,
    PlannerHandoff,
    WorkerAssignment,
    WorkerTask,
)


class ChiefApiService:
    """Keep Chief coordinators addressable by run ID for the API process."""

    def __init__(self):
        self._chiefs: dict[str, ChiefCoordinator] = {}

    def accept_handoff(self, handoff: PlannerHandoff) -> list[WorkerTask]:
        chief = ChiefCoordinator(Path(handoff.repository_path))
        tasks = chief.create_tasks_from_handoff(handoff)
        self._chiefs[handoff.run_id] = chief
        return tasks

    def integration_report(self, run_id: str) -> IntegrationReport:
        chief = self._chiefs.get(run_id)
        if chief is None:
            raise KeyError(run_id)
        return chief.integration_report(run_id)

    def delegate(self, run_id: str, *, provider: str) -> list[WorkerAssignment]:
        chief = self._chiefs.get(run_id)
        if chief is None:
            raise KeyError(run_id)
        raw = chief.state_store.get_handoff(run_id)
        if raw is None:
            raise KeyError(run_id)
        return chief.delegate_tasks(PlannerHandoff.model_validate(raw), provider=provider)

    def events(self, run_id: str) -> list[dict[str, object]]:
        chief = self._chiefs.get(run_id)
        if chief is None:
            raise KeyError(run_id)
        return chief.state_store.events_for_run(run_id)

    def status(self, run_id: str) -> dict[str, object]:
        chief = self._chiefs.get(run_id)
        if chief is None:
            raise KeyError(run_id)
        return {
            "run": chief.state_store.get_run(run_id),
            "tasks": chief.state_store.tasks_for_run(run_id),
            "workers": chief.state_store.workers_for_run(run_id),
            "results": chief.state_store.worker_results_for_run(run_id),
        }
