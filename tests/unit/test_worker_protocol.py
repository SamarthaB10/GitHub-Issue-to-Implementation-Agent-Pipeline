import pytest

from agents.worker_protocol import SkillTraceGate
from schemas.runtime import SkillTrace, WorkerAssignment, WorkerResult


def trace(skill, phase, *, sequence=1, evidence=None, status="completed"):
    return SkillTrace(
        sequence=sequence,
        skill=skill,
        phase=phase,
        status=status,
        evidence=evidence or {},
    )


def complete_trace():
    return [
        trace("implement", "started", sequence=1),
        trace("tdd", "red", sequence=2, evidence={"test": "test_new_behavior"}),
        trace("tdd", "green", sequence=3, evidence={"test": "test_new_behavior"}),
        trace("code-review", "reviewed", sequence=4, evidence={"review": "passed"}),
    ]


def test_skill_trace_gate_accepts_the_required_worker_pipeline():
    result = WorkerResult(
        run_id="run-1",
        worker_id="worker-1",
        task_id="task-1",
        status="completed",
        commit="abc1234",
        changed_files=["src/app.py"],
        checks=[{"name": "pytest", "status": "passed"}],
        skill_trace=complete_trace(),
    )

    decision = SkillTraceGate().check(result)

    assert decision.accepted is True
    assert decision.missing_phases == []


def test_skill_trace_gate_rejects_a_result_without_review_trace():
    result = WorkerResult(
        run_id="run-1",
        worker_id="worker-1",
        task_id="task-1",
        status="completed",
        commit="abc1234",
        changed_files=["src/app.py"],
        checks=[],
        skill_trace=complete_trace()[:-1],
    )

    decision = SkillTraceGate().check(result)

    assert decision.accepted is False
    assert decision.missing_phases == ["code-review:reviewed"]


def test_skill_trace_gate_rejects_required_phases_in_wrong_order():
    result = WorkerResult(
        run_id="run-1",
        worker_id="worker-1",
        task_id="task-1",
        status="completed",
        commit="abc1234",
        skill_trace=list(reversed(complete_trace())),
    )

    decision = SkillTraceGate().check(result)

    assert decision.accepted is False
    assert "Skill trace sequence is not ordered." in decision.violations


def test_skill_trace_rejects_unknown_phase():
    with pytest.raises(ValueError):
        SkillTrace(
            sequence=1,
            skill="implement",
            phase="cleanup",
            status="completed",
            evidence={},
        )


def test_skill_trace_gate_rejects_a_changed_file_outside_assignment_scope(tmp_path):
    assignment = WorkerAssignment(
        run_id="run-1",
        worker_id="worker-1",
        task_id="task-1",
        project_workspace=str(tmp_path),
        worktree_path=str(tmp_path / "worktree"),
        branch="chief/run-1/worker-1",
        base_commit="abc1234",
        assigned_paths=["src/**"],
    )
    result = WorkerResult(
        run_id="run-1",
        worker_id="worker-1",
        task_id="task-1",
        status="completed",
        commit="abc1234",
        changed_files=["README.md"],
        skill_trace=complete_trace(),
    )

    decision = SkillTraceGate().check(result, assignment)

    assert decision.accepted is False
    assert "outside assigned scope" in decision.violations[0]
