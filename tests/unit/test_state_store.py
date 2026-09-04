import sqlite3

import pytest

from agents.state_store import ChiefStateStore, StateStoreError
from schemas.runtime import QueueEntry, WorkerAssignment, WorkerTask
from tests.unit.test_handoff import make_handoff


def make_task():
    return WorkerTask(
        run_id="run-1",
        task_id="task-1",
        title="Implement authentication change",
        description="Update the authentication path.",
        acceptance_criteria=["Valid users can sign in."],
        assigned_paths=["src/**"],
        required_checks=[["python", "-m", "pytest"]],
    )


def make_assignment(tmp_path):
    return WorkerAssignment(
        run_id="run-1",
        worker_id="worker-1",
        task_id="task-1",
        project_workspace=str(tmp_path / "project"),
        worktree_path=str(tmp_path / "worker"),
        branch="chief/run-1/worker-1",
        base_commit="abc1234",
        assigned_paths=["src/**"],
    )


def test_state_store_persists_run_tasks_workers_and_events(tmp_path):
    store = ChiefStateStore(tmp_path)
    store.initialize()
    store.create_run("run-1", base_commit="abc1234")
    task = make_task()
    store.record_task(task)
    assignment = make_assignment(tmp_path)
    store.record_worker(assignment)
    entry = QueueEntry(
        queue_id="run-1/worker-1/1",
        run_id="run-1",
        worker_id="worker-1",
        sequence=1,
        priority="workflow",
        kind="task",
        task_id="task-1",
        title=task.title,
        description=task.description,
    )
    store.record_queue_entry(entry)
    store.record_event("run-1", "worker_started", {"worker_id": "worker-1"})

    reopened = ChiefStateStore(tmp_path)
    reopened.initialize()

    run = reopened.get_run("run-1")
    assert run is not None
    assert run["base_commit"] == "abc1234"
    assert reopened.get_task("task-1")["title"] == task.title
    assert reopened.get_worker("worker-1")["branch"] == assignment.branch
    assert reopened.get_queue_entry(entry.queue_id)["task_id"] == "task-1"
    assert reopened.events_for_run("run-1")[-1]["event_type"] == "worker_started"


def test_state_store_rejects_unknown_future_schema(tmp_path):
    db_path = tmp_path / ".chief" / "chief.sqlite3"
    db_path.parent.mkdir()
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA user_version = 999")
    connection.commit()
    connection.close()

    with pytest.raises(StateStoreError, match="newer schema"):
        ChiefStateStore(tmp_path).initialize()


def test_state_store_persists_and_reopens_a_planner_handoff(tmp_path):
    store = ChiefStateStore(tmp_path)
    store.initialize()
    store.create_run("run-1", base_commit="abc1234")
    handoff = make_handoff()
    handoff = handoff.model_copy(update={"repository_path": str(tmp_path)})

    store.record_handoff(handoff)

    reopened = ChiefStateStore(tmp_path)
    assert reopened.get_handoff("run-1")["schema_version"] == 1
