import pytest

from agents.handoff import build_planner_handoff
from tests.unit.test_handoff import make_handoff


def test_handoff_builder_exports_approved_graph_state():
    expected = make_handoff()
    state = {
        "issue": {
            "repository": expected.repository,
            "number": 1,
            "title": "Fix login",
            "body": "Valid users cannot sign in.",
        },
        "repository_path": expected.repository_path,
        "issue_brief": expected.issue_brief,
        "repository_map": expected.repository_map,
        "implementation_plan": expected.implementation_plan,
        "plan_approval": expected.plan_approval,
    }

    result = build_planner_handoff(state, base_commit="abc1234", created_at=expected.created_at)

    assert result.run_id == "planner-run"
    assert result.base_commit == "abc1234"


def test_handoff_builder_requires_all_planner_artifacts():
    with pytest.raises(ValueError, match="repository_map"):
        build_planner_handoff(
            {"issue": {}, "repository_path": "/tmp"},
            base_commit="abc1234",
        )
