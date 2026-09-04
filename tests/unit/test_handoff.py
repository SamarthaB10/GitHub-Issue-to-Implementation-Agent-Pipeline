from pathlib import Path

import pytest

from schemas.approval import PlanApprovalDecision
from schemas.issue import IssueBrief
from schemas.planning import ImplementationPlan, ImplementationStep
from schemas.repository import RelevantFile, RepositoryMap
from schemas.runtime import PlannerHandoff


def make_handoff(action="approve"):
    return PlannerHandoff(
        run_id="run-1",
        repository="example/project",
        repository_path=str(Path.cwd()),
        base_commit="abc1234",
        issue_brief=IssueBrief(
            summary="Fix login",
            problem_statement="Valid users cannot sign in.",
            requirements=["Restore login."],
            acceptance_criteria=["A valid user can sign in."],
            in_scope=["Login"],
            out_of_scope=["Registration"],
            is_actionable=True,
            actionability_reason="Clear.",
        ),
        repository_map=RepositoryMap(
            summary="Auth is in src/auth.py.",
            relevant_files=[RelevantFile(path="src/auth.py", reason="Login")],
        ),
        implementation_plan=ImplementationPlan(
            summary="Fix login",
            approach="Update auth handler.",
            steps=[
                ImplementationStep(
                    order=1,
                    description="Fix login.",
                    affected_files=["src/auth.py"],
                    rationale="Restores login.",
                )
            ],
            ready_for_approval=True,
        ),
        plan_approval=PlanApprovalDecision(action=action),
        created_at="2026-09-04T00:00:00+00:00",
    )


def test_planner_handoff_accepts_only_approved_ready_artifacts():
    handoff = make_handoff()

    assert handoff.schema_version == 1
    assert handoff.implementation_plan.steps[0].affected_files == ["src/auth.py"]


def test_planner_handoff_rejects_non_approved_decisions():
    with pytest.raises(ValueError, match="Only approved plans"):
        make_handoff("cancel")
