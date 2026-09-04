from pathlib import Path

from agents.chief import ChiefCoordinator
from agents.skill_catalog import SkillCatalog
from schemas.runtime import (
    CheckObservation,
    SkillTrace,
    WorkerAssignment,
    WorkerResult,
    WorkerTask,
)

PROJECT_ROOT = Path(__file__).parents[2]


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


def make_result(*, complete):
    traces = [
        SkillTrace(sequence=1, skill="implement", phase="started", status="completed"),
        SkillTrace(sequence=2, skill="tdd", phase="red", status="completed"),
        SkillTrace(sequence=3, skill="tdd", phase="green", status="completed"),
    ]
    if complete:
        traces.append(
            SkillTrace(
                sequence=4,
                skill="code-review",
                phase="reviewed",
                status="completed",
            )
        )
    return WorkerResult(
        run_id="run-1",
        worker_id="worker-1",
        task_id="task-1",
        status="completed",
        commit="abc1234" if complete else None,
        changed_files=["src/app.py"],
        checks=[CheckObservation(name="pytest", status="passed")],
        skill_trace=traces,
    )


def test_chief_turns_a_task_into_a_queue_entry_and_accepts_traced_result(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    chief = ChiefCoordinator(
        project,
        skill_catalog=SkillCatalog.from_project(PROJECT_ROOT),
    )
    chief.start_run("run-1", base_commit="abc1234")
    assignment = make_assignment(tmp_path)
    task = make_task()

    entry = chief.assign_task(task, assignment, sequence=1)
    decision = chief.accept_worker_result(make_result(complete=True))

    assert entry.queue_id == "run-1/worker-1/1"
    assert decision.accepted is True
    assert (
        project / ".chief" / "workers" / "worker-1" / "context" / "sub_agents.md"
    ).is_file()
    assert (
        project / ".chief" / "workers" / "worker-1" / "context" / "context.agent"
    ).is_file()
    assert chief.state_store.events_for_run("run-1")[-1]["event_type"] == (
        "worker_result_accepted"
    )


def test_chief_rejects_worker_result_without_required_skill_trace(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    chief = ChiefCoordinator(
        project,
        skill_catalog=SkillCatalog.from_project(PROJECT_ROOT),
    )
    chief.start_run("run-1", base_commit="abc1234")

    decision = chief.accept_worker_result(make_result(complete=False))

    assert decision.accepted is False
    assert chief.state_store.events_for_run("run-1")[-1]["event_type"] == (
        "worker_result_rejected"
    )
