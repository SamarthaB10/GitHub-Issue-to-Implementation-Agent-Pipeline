import json

from agents.chief import ChiefCoordinator
from agents.lifecycle import WorkerLifecycleManager
from agents.providers import WorkerExecution
from schemas.runtime import WorkerAssignment


class FakeProcess:
    def start(self):
        self.started = True

    def poll(self):
        return None

    def wait(self, timeout_seconds):
        return WorkerExecution("completed", 0, "worker output", "")

    def stop(self):
        self.stopped = True


class FakeProvider:
    name = "codex"

    def build_launch(self, assignment):
        from agents.providers import WorkerLaunch

        return WorkerLaunch(("fake-worker",), "prompt", {})


def make_assignment(tmp_path):
    worktree = tmp_path / "worker"
    worktree.mkdir()
    return WorkerAssignment(
        run_id="run-1",
        worker_id="worker-1",
        task_id="task-1",
        project_workspace=str(tmp_path),
        worktree_path=str(worktree),
        branch="chief/run-1/worker-1",
        base_commit="abc1234",
        assigned_paths=["src/**"],
    )


def test_lifecycle_loads_worker_result_and_routes_it_through_chief(tmp_path):
    assignment = make_assignment(tmp_path)
    result_path = tmp_path / "worker" / ".chief-worker" / "result.json"
    result_path.parent.mkdir()
    result_path.write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "worker_id": "worker-1",
                "task_id": "task-1",
                "status": "completed",
                "commit": "abc1234",
                "changed_files": ["src/app.py"],
                "skill_trace": [
                    {"sequence": 1, "skill": "implement", "phase": "started", "status": "completed"},
                    {"sequence": 2, "skill": "tdd", "phase": "red", "status": "completed"},
                    {"sequence": 3, "skill": "tdd", "phase": "green", "status": "completed"},
                    {"sequence": 4, "skill": "code-review", "phase": "reviewed", "status": "completed"},
                ],
            }
        ),
        encoding="utf-8",
    )
    chief = ChiefCoordinator(tmp_path)
    chief.start_run("run-1", base_commit="abc1234")
    lifecycle = WorkerLifecycleManager(
        chief,
        process_factory=lambda assignment, launch, result_path: FakeProcess(),
    )

    lifecycle.start(assignment, FakeProvider())
    outcome = lifecycle.wait("worker-1", timeout_seconds=10)

    assert outcome.accepted is True
    assert outcome.execution.status == "completed"
    assert chief.integration_report("run-1").status == "ready_for_human"
