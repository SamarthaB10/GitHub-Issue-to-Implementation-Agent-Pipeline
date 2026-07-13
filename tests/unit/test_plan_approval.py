import pytest
from pydantic import ValidationError

from agents.graph.approvals import plan_approval_node
from schemas.approval import PlanApprovalDecision
from schemas.issue import IssueInput


def test_request_changes_requires_feedback():
    with pytest.raises(ValidationError, match="feedback is required"):
        PlanApprovalDecision(action="request_changes")


def test_approval_decision_rejects_extra_fields():
    with pytest.raises(ValidationError, match="unexpected"):
        PlanApprovalDecision.model_validate(
            {
                "action": "approve",
                "unexpected": "value",
            }
        )


def test_plan_approval_node_requires_implementation_plan():
    with pytest.raises(ValueError, match="requires implementation_plan"):
        plan_approval_node(
            {
                "issue": IssueInput(
                    repository="example/project",
                    number=42,
                    title="Fix authentication failure",
                ),
                "repository_path": "/tmp/example-project",
            }
        )
