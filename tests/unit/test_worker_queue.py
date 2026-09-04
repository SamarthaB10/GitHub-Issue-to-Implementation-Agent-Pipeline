
from agents.worker_queue import WorkerQueue
from schemas.runtime import QueueEntry, WorkerTask


def make_task():
    return WorkerTask(
        run_id="run-1",
        task_id="task-1",
        title="Implement authentication change",
        description="Update the authentication path and regression tests.",
        acceptance_criteria=["Valid users can sign in."],
        assigned_paths=["src/**", "tests/**"],
        required_checks=[["python", "-m", "pytest"]],
    )


def test_chief_appends_ticket_to_authoritative_and_worker_queues(tmp_path):
    project = tmp_path / "project"
    worktree = tmp_path / "worktree"
    project.mkdir()
    worktree.mkdir()
    queue = WorkerQueue(project, worktree, "worker-1")

    entry = queue.enqueue(make_task(), sequence=1)

    assert entry.queue_id == "run-1/worker-1/1"
    authoritative = project / ".chief" / "workers" / "worker-1" / "sub_agent_queue.md"
    worker_local = worktree / ".chief-worker" / "sub_agent_queue.md"
    assert authoritative.is_file()
    assert worker_local.is_file()
    assert authoritative.read_text(encoding="utf-8") == worker_local.read_text(
        encoding="utf-8"
    )
    assert "Implement authentication change" in authoritative.read_text(
        encoding="utf-8"
    )


def test_queue_is_append_only_and_change_request_points_to_prior_entry(tmp_path):
    project = tmp_path / "project"
    worktree = tmp_path / "worktree"
    project.mkdir()
    worktree.mkdir()
    queue = WorkerQueue(project, worktree, "worker-1")
    queue.enqueue(make_task(), sequence=1)

    change = QueueEntry(
        queue_id="run-1/worker-1/2",
        run_id="run-1",
        worker_id="worker-1",
        sequence=2,
        priority="workflow",
        kind="change_request",
        task_id="task-1",
        title="Add authentication integration coverage",
        description="Add the missing integration test.",
        supersedes_entry_id="run-1/worker-1/1",
    )
    queue.append(change)

    content = (project / ".chief" / "workers" / "worker-1" / "sub_agent_queue.md").read_text(
        encoding="utf-8"
    )
    assert content.index("run-1/worker-1/1") < content.index("run-1/worker-1/2")
    assert "Supersedes: run-1/worker-1/1" in content
