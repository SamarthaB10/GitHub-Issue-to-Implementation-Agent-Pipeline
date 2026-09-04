
import shutil
import subprocess
from pathlib import Path

from agents.chief import ChiefCoordinator
from schemas.runtime import WorkerResult
from tests.unit.test_handoff import make_handoff

PROJECT_ROOT = Path(__file__).parents[2]


def test_chief_persists_approved_handoff_and_creates_tasks(tmp_path):
    handoff = make_handoff()
    handoff = handoff.model_copy(update={"repository_path": str(tmp_path)})
    chief = ChiefCoordinator(tmp_path)

    tasks = chief.create_tasks_from_handoff(handoff)

    assert tasks[0].task_id == "run-1/step-1"
    assert chief.state_store.get_handoff("run-1")["schema_version"] == 1
    assert chief.state_store.get_task("run-1/step-1")["title"].startswith("Step 1")
    assert chief.state_store.get_run("run-1")["status"] == "delegating"


def test_chief_integration_report_requires_human_review(tmp_path):
    chief = ChiefCoordinator(tmp_path)
    chief.start_run("run-1", base_commit="abc1234")

    report = chief.integration_report("run-1")

    assert report.status == "blocked"
    assert "Wait for" in report.next_action


def test_integration_report_blocks_a_result_that_fails_the_skill_gate(tmp_path):
    chief = ChiefCoordinator(tmp_path)
    chief.start_run("run-1", base_commit="abc1234")
    chief.accept_worker_result(
        WorkerResult(
            run_id="run-1",
            worker_id="worker-1",
            task_id="task-1",
            status="completed",
            commit="abc1234",
            changed_files=["src/app.py"],
        )
    )

    report = chief.integration_report("run-1")

    assert report.status == "blocked"
    assert "implement:started" in report.errors


def test_chief_delegation_creates_worktree_queue_and_worker_context(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=project,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=project, check=True
    )
    (project / "README.md").write_text("base\n", encoding="utf-8")
    shutil.copytree(PROJECT_ROOT / "docs" / "skills", project / "docs" / "skills")
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=project, check=True)
    base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    handoff = make_handoff().model_copy(
        update={"repository_path": str(project), "base_commit": base_commit}
    )

    assignments = ChiefCoordinator(project).delegate_tasks(handoff)

    assignment = assignments[0]
    worker_root = project / ".chief" / "worktrees" / "run-1" / "worker-1"
    assert (project / ".chief" / "workers" / "worker-1" / "sub_agent_queue.md").is_file()
    assert (project / ".chief" / "workers" / "worker-1" / "context" / "context.agent").is_file()
    assert worker_root.is_dir()
    assert (worker_root / ".chief-worker" / "context" / "sub_agents.md").is_file()
    assert assignment.branch == "chief/run-1/worker-1"
