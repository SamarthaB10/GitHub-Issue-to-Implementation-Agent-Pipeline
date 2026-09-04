from agents.chief import ChiefCoordinator
from agents.lifecycle import WorkerLifecycleManager
from schemas.runtime import WorkerTask


def test_lifecycle_discovers_assignments_without_results_after_restart(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    chief = ChiefCoordinator(project)
    chief.start_run("run-1", base_commit="abc1234")
    task = WorkerTask(
        run_id="run-1",
        task_id="task-1",
        title="Task",
        description="Work",
        acceptance_criteria=["Done"],
        assigned_paths=["src/**"],
    )
    assignment = {
        "run_id": "run-1",
        "worker_id": "worker-1",
        "task_id": "task-1",
        "project_workspace": str(project),
        "worktree_path": str(tmp_path / "worker"),
        "branch": "chief/run-1/worker-1",
        "base_commit": "abc1234",
        "assigned_paths": ["src/**"],
    }
    from schemas.runtime import WorkerAssignment

    chief.state_store.record_task(task)
    chief.state_store.record_worker(WorkerAssignment.model_validate(assignment))

    recovered = WorkerLifecycleManager(chief).recoverable_assignments("run-1")

    assert [item.worker_id for item in recovered] == ["worker-1"]
