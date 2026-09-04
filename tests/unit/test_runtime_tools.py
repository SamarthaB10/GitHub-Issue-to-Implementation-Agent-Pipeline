import hashlib
import subprocess
import sys

import pytest

from agents.tools.runtime_tools import RuntimeToolService, RuntimeToolViolation
from schemas.runtime import WorkerAssignment


def create_git_worktree(tmp_path, *, branch="chief/run-1/worker-1"):
    project = tmp_path / "project"
    project.mkdir()
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("return 'old'\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=project,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=project,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=project, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=project, check=True)

    worktree = tmp_path / "worker-1"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", branch, str(worktree), "HEAD"],
        cwd=project,
        check=True,
    )
    return project, worktree


def assignment_for(project, worktree, *, branch="chief/run-1/worker-1"):
    return WorkerAssignment(
        run_id="run-1",
        worker_id="worker-1",
        task_id="task-1",
        project_workspace=str(project),
        worktree_path=str(worktree),
        branch=branch,
        base_commit="HEAD",
        assigned_paths=["src/**"],
        approved_checks=[[sys.executable, "-c", "print('ok')"]],
    )


def test_runtime_worker_can_apply_hash_checked_patch(tmp_path):
    project, worktree = create_git_worktree(tmp_path)
    old_content = (worktree / "src" / "app.py").read_bytes()
    expected_hash = hashlib.sha256(old_content).hexdigest()
    service = RuntimeToolService(assignment_for(project, worktree))

    result = service.apply_file_patch(
        patch=(
            "diff --git a/src/app.py b/src/app.py\n"
            "index 7b8f1c1..f0f8f8a 100644\n"
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -1 +1 @@\n"
            "-return 'old'\n"
            "+return 'new'\n"
        ),
        expected_files={"src/app.py": expected_hash},
    )

    assert result.status == "applied"
    assert (worktree / "src" / "app.py").read_text(encoding="utf-8") == (
        "return 'new'\n"
    )


def test_runtime_worker_rejects_scope_escape_before_edit(tmp_path):
    project, worktree = create_git_worktree(tmp_path)
    service = RuntimeToolService(assignment_for(project, worktree))

    with pytest.raises(RuntimeToolViolation, match="outside assigned scope"):
        service.apply_file_patch(
            patch=(
                "diff --git a/README.md b/README.md\n"
                "new file mode 100644\n"
                "--- /dev/null\n"
                "+++ b/README.md\n"
                "@@ -0,0 +1 @@\n"
                "+new\n"
            ),
            expected_files={"README.md": None},
        )

    assert not (worktree / "README.md").exists()


def test_runtime_worker_rejects_stale_hash(tmp_path):
    project, worktree = create_git_worktree(tmp_path)
    service = RuntimeToolService(assignment_for(project, worktree))

    with pytest.raises(RuntimeToolViolation, match="hash does not match"):
        service.apply_file_patch(
            patch=(
                "diff --git a/src/app.py b/src/app.py\n"
                "--- a/src/app.py\n"
                "+++ b/src/app.py\n"
                "@@ -1 +1 @@\n"
                "-return 'old'\n"
                "+return 'new'\n"
            ),
            expected_files={"src/app.py": "stale"},
        )


def test_runtime_worker_rejects_symlink_patch_mode(tmp_path):
    project, worktree = create_git_worktree(tmp_path)
    service = RuntimeToolService(assignment_for(project, worktree))

    with pytest.raises(RuntimeToolViolation, match="regular file"):
        service.apply_file_patch(
            patch=(
                "diff --git a/src/link b/src/link\n"
                "new file mode 120000\n"
                "--- /dev/null\n"
                "+++ b/src/link\n"
                "@@ -0,0 +1 @@\n"
                "+../outside\n"
            ),
            expected_files={"src/link": None},
        )


def test_runtime_worker_runs_only_exact_approved_check(tmp_path):
    project, worktree = create_git_worktree(tmp_path)
    service = RuntimeToolService(assignment_for(project, worktree))

    result = service.run_check([sys.executable, "-c", "print('ok')"])

    assert result.status == "passed"
    assert result.exit_code == 0
    assert result.stdout.strip() == "ok"

    with pytest.raises(RuntimeToolViolation, match="not approved"):
        service.run_check([sys.executable, "-c", "print('not approved')"])


def test_runtime_worker_records_only_assigned_skill_trace(tmp_path):
    project, worktree = create_git_worktree(tmp_path)
    service = RuntimeToolService(assignment_for(project, worktree))

    trace = service.record_skill_trace(
        skill="tdd",
        phase="red",
        evidence={"test": "test_new_behavior"},
    )

    assert trace.sequence == 1
    assert service.audit_events[-1].event_type == "skill_trace"
    with pytest.raises(RuntimeToolViolation, match="not in the assigned route"):
        service.record_skill_trace(skill="triage", phase="started")


def test_runtime_worker_commit_is_limited_to_owned_branch(tmp_path):
    project, worktree = create_git_worktree(tmp_path)
    (worktree / "src" / "app.py").write_text("return 'new'\n", encoding="utf-8")
    service = RuntimeToolService(assignment_for(project, worktree))

    result = service.git_commit("Implement new behavior")

    assert result.status == "committed"
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=worktree,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert branch == "chief/run-1/worker-1"


def test_main_branch_is_rejected(tmp_path):
    project, worktree = create_git_worktree(tmp_path, branch="main-worker")
    assignment = assignment_for(project, worktree, branch="main-worker")
    assignment.protected_branches = ["main-worker"]
    service = RuntimeToolService(assignment)

    with pytest.raises(RuntimeToolViolation, match="protected branch"):
        service.git_status()
