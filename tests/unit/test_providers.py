import json
import sys

from agents.providers import CommandProvider, SubprocessWorkerProcess
from schemas.runtime import WorkerAssignment


def assignment(tmp_path):
    worktree = tmp_path / "worktree"
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


def test_command_provider_is_provider_neutral_and_does_not_include_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value")
    provider = CommandProvider("codex", ("codex", "exec"))

    launch = provider.build_launch(assignment(tmp_path))

    assert launch.argv[:2] == ("codex", "exec")
    assert "secret-value" not in launch.prompt
    assert "OPENAI_API_KEY" not in launch.environment


def test_subprocess_worker_writes_bounded_output_and_reports_completion(tmp_path):
    result_path = tmp_path / "result.json"
    code = (
        "import json, os; "
        "open(os.environ['CHIEF_RESULT_PATH'], 'w').write(json.dumps({'ok': True}))"
    )
    worker_assignment = assignment(tmp_path)
    process = SubprocessWorkerProcess(
        worker_assignment,
        (sys.executable, "-c", code),
        result_path=result_path,
        context_dir=tmp_path / "context",
    )

    process.start()
    outcome = process.wait(5)

    assert outcome.status == "completed"
    assert outcome.exit_code == 0
    assert json.loads(result_path.read_text(encoding="utf-8"))["ok"] is True
