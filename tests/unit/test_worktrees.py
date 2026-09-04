import subprocess

import pytest

from agents.worktrees import WorktreeError, WorktreeManager


def git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )


def make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-qm", "base")
    return repo


def test_worktree_manager_creates_a_worker_assignment_from_a_commit(tmp_path):
    repo = make_repo(tmp_path)
    base_commit = git(repo, "rev-parse", "HEAD").stdout.strip()

    assignment = WorktreeManager(repo).create_assignment(
        "run-1",
        "task-1",
        "worker-1",
        base_commit=base_commit,
        assigned_paths=["src/**"],
    )

    assert assignment.branch == "chief/run-1/worker-1"
    assert (tmp_path / "repo" / ".chief" / "worktrees" / "run-1" / "worker-1").is_dir()
    assert git(assignment.worktree_path, "branch", "--show-current").stdout.strip() == assignment.branch


def test_worktree_manager_rejects_invalid_base_commit(tmp_path):
    repo = make_repo(tmp_path)

    with pytest.raises(WorktreeError, match="base commit"):
        WorktreeManager(repo).create_assignment(
            "run-1",
            "task-1",
            "worker-1",
            base_commit="missing",
            assigned_paths=["src/**"],
        )
