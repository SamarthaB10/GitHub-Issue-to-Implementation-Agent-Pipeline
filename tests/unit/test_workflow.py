import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import agents.graph.workflow as workflow_module
from agents.graph.routing import (
    route_after_implementation_plan,
    route_after_issue_analysis,
    route_after_plan_approval,
)
from schemas.issue import IssueBrief, IssueInput
from schemas.planning import ImplementationPlan, ImplementationStep, PlannedTest
from schemas.repository import RelevantFile, RepositoryMap


def make_issue() -> IssueInput:
    return IssueInput(
        repository="example/project",
        number=42,
        title="Fix authentication failure",
        body="Valid users receive a server error when signing in.",
        labels=["bug", "agent-ready"],
    )


def make_brief(*, actionable: bool) -> IssueBrief:
    return IssueBrief(
        summary="Fix valid-user authentication.",
        problem_statement="Valid users cannot sign in.",
        requirements=["Restore authentication for valid users."],
        acceptance_criteria=["A valid user can sign in successfully."],
        in_scope=["Authentication failure handling."],
        out_of_scope=["Account registration."],
        open_questions=[] if actionable else ["Which login flow is affected?"],
        is_actionable=actionable,
        actionability_reason=(
            "Expected behavior is clear."
            if actionable
            else "The affected login flow is unspecified."
        ),
    )


def make_repository_map() -> RepositoryMap:
    return RepositoryMap(
        summary="Authentication is implemented in the auth module.",
        relevant_files=[
            RelevantFile(
                path="src/auth.py",
                reason="Contains the login handler.",
                important_symbols=["login"],
            )
        ],
    )


def make_implementation_plan(*, ready: bool = True) -> ImplementationPlan:
    return ImplementationPlan(
        summary="Correct authentication failure handling.",
        approach="Update the existing login handler and add regression coverage.",
        steps=[
            ImplementationStep(
                order=1,
                description="Correct the valid-user login path.",
                affected_files=["src/auth.py"],
                rationale="Satisfies the required authentication behavior.",
            )
        ],
        planned_tests=[
            PlannedTest(
                description="Verify a valid user can sign in.",
                test_type="unit",
                target_file="tests/test_auth.py",
            )
        ],
        blocking_questions=(
            [] if ready else ["Which authentication flow should change?"]
        ),
        ready_for_approval=ready,
    )


def install_fake_nodes(
    monkeypatch,
    *,
    actionable: bool,
    explorer_calls: list,
    planner_calls: list,
    planner_ready: bool = True,
):
    async def fake_issue_analyst(state):
        brief = make_brief(actionable=actionable)
        return {
            "issue_brief": brief,
            "status": (
                "ready_for_exploration"
                if brief.is_actionable
                else "needs_clarification"
            ),
        }

    async def fake_repository_explorer(state):
        explorer_calls.append(state["issue"].number)
        return {
            "repository_map": make_repository_map(),
            "status": "repository_explored",
        }

    async def fake_implementation_planner(state):
        planner_calls.append(state["repository_map"].summary)
        return {
            "implementation_plan": make_implementation_plan(ready=planner_ready),
            "status": (
                "ready_for_plan_review"
                if planner_ready
                else "needs_clarification"
            ),
        }

    monkeypatch.setattr(
        workflow_module,
        "issue_analyst_node",
        fake_issue_analyst,
    )
    monkeypatch.setattr(
        workflow_module,
        "repository_explorer_node",
        fake_repository_explorer,
    )
    monkeypatch.setattr(
        workflow_module,
        "implementation_planner_node",
        fake_implementation_planner,
    )


def make_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


async def start_actionable_workflow(monkeypatch, thread_id: str):
    explorer_calls = []
    planner_calls = []
    install_fake_nodes(
        monkeypatch,
        actionable=True,
        explorer_calls=explorer_calls,
        planner_calls=planner_calls,
    )
    graph = workflow_module.build_workflow()
    config = make_config(thread_id)
    result = await graph.ainvoke(
        {
            "issue": make_issue(),
            "repository_path": "/tmp/example-project",
        },
        config=config,
    )
    return graph, config, result, explorer_calls, planner_calls


@pytest.mark.asyncio
async def test_actionable_issue_pauses_for_plan_approval(monkeypatch):
    graph, config, result, explorer_calls, planner_calls = (
        await start_actionable_workflow(monkeypatch, "approval-pause")
    )

    assert explorer_calls == [42]
    assert len(planner_calls) == 1
    assert result["status"] == "ready_for_plan_review"
    assert result["implementation_plan"] == make_implementation_plan()
    assert result["__interrupt__"][0].value["type"] == "plan_approval"
    assert result["__interrupt__"][0].value["allowed_actions"] == [
        "approve",
        "request_changes",
        "cancel",
    ]
    assert (await graph.aget_state(config)).next == ("plan_approval",)


@pytest.mark.asyncio
async def test_approve_resumes_and_finishes_workflow(monkeypatch):
    graph, config, _, _, _ = await start_actionable_workflow(
        monkeypatch,
        "approval-approve",
    )

    result = await graph.ainvoke(
        Command(resume={"action": "approve"}),
        config=config,
    )

    assert result["status"] == "plan_approved"
    assert result["plan_approval"].action == "approve"
    assert "__interrupt__" not in result


@pytest.mark.asyncio
async def test_request_changes_replans_and_pauses_again(monkeypatch):
    graph, config, _, _, planner_calls = await start_actionable_workflow(
        monkeypatch,
        "approval-revise",
    )

    revised = await graph.ainvoke(
        Command(
            resume={
                "action": "request_changes",
                "feedback": "Add an integration test step.",
            }
        ),
        config=config,
    )

    assert len(planner_calls) == 2
    assert revised["status"] == "ready_for_plan_review"
    assert revised["plan_feedback"] == "Add an integration test step."
    assert revised["plan_approval"].action == "request_changes"
    assert revised["__interrupt__"][0].value["type"] == "plan_approval"

    approved = await graph.ainvoke(
        Command(resume={"action": "approve"}),
        config=config,
    )
    assert approved["status"] == "plan_approved"


@pytest.mark.asyncio
async def test_cancel_resumes_and_finishes_workflow(monkeypatch):
    graph, config, _, _, _ = await start_actionable_workflow(
        monkeypatch,
        "approval-cancel",
    )

    result = await graph.ainvoke(
        Command(resume={"action": "cancel", "feedback": "Not in scope."}),
        config=config,
    )

    assert result["status"] == "cancelled"
    assert result["plan_approval"].action == "cancel"
    assert result["plan_feedback"] == "Not in scope."


@pytest.mark.asyncio
async def test_invalid_decision_pauses_again_with_validation_error(monkeypatch):
    graph, config, _, _, _ = await start_actionable_workflow(
        monkeypatch,
        "approval-invalid",
    )

    invalid = await graph.ainvoke(
        Command(resume={"action": "request_changes"}),
        config=config,
    )

    assert invalid["__interrupt__"][0].value["type"] == "plan_approval"
    assert "validation_error" in invalid["__interrupt__"][0].value

    approved = await graph.ainvoke(
        Command(resume={"action": "approve"}),
        config=config,
    )
    assert approved["status"] == "plan_approved"


@pytest.mark.asyncio
async def test_blocked_plan_stops_before_approval(monkeypatch):
    explorer_calls = []
    planner_calls = []
    install_fake_nodes(
        monkeypatch,
        actionable=True,
        explorer_calls=explorer_calls,
        planner_calls=planner_calls,
        planner_ready=False,
    )
    graph = workflow_module.build_workflow()

    result = await graph.ainvoke(
        {
            "issue": make_issue(),
            "repository_path": "/tmp/example-project",
        },
        config=make_config("blocked-plan"),
    )

    assert result["status"] == "needs_clarification"
    assert result["implementation_plan"].ready_for_approval is False
    assert "__interrupt__" not in result


@pytest.mark.asyncio
async def test_non_actionable_issue_stops_before_exploration(monkeypatch):
    explorer_calls = []
    planner_calls = []
    install_fake_nodes(
        monkeypatch,
        actionable=False,
        explorer_calls=explorer_calls,
        planner_calls=planner_calls,
    )
    graph = workflow_module.build_workflow()

    result = await graph.ainvoke(
        {
            "issue": make_issue(),
            "repository_path": "/tmp/example-project",
        },
        config=make_config("non-actionable"),
    )

    assert explorer_calls == []
    assert planner_calls == []
    assert result["issue_brief"].is_actionable is False
    assert result["status"] == "needs_clarification"
    assert "repository_map" not in result
    assert "implementation_plan" not in result


def test_routing_requires_expected_state_artifacts():
    with pytest.raises(ValueError, match="requires issue_brief"):
        route_after_issue_analysis(
            {
                "issue": make_issue(),
                "repository_path": "/tmp/example-project",
            }
        )

    with pytest.raises(ValueError, match="requires plan_approval"):
        route_after_plan_approval(
            {
                "issue": make_issue(),
                "repository_path": "/tmp/example-project",
            }
        )

    with pytest.raises(ValueError, match="requires implementation_plan"):
        route_after_implementation_plan(
            {
                "issue": make_issue(),
                "repository_path": "/tmp/example-project",
            }
        )


def test_workflow_uses_default_in_memory_checkpointer(monkeypatch):
    install_fake_nodes(
        monkeypatch,
        actionable=True,
        explorer_calls=[],
        planner_calls=[],
    )

    graph = workflow_module.build_workflow()

    assert isinstance(graph.checkpointer, InMemorySaver)


@pytest.mark.asyncio
async def test_workflow_accepts_custom_checkpointer(monkeypatch):
    install_fake_nodes(
        monkeypatch,
        actionable=True,
        explorer_calls=[],
        planner_calls=[],
    )
    checkpointer = InMemorySaver()
    graph = workflow_module.build_workflow(checkpointer=checkpointer)
    config = make_config("custom-checkpointer")

    result = await graph.ainvoke(
        {
            "issue": make_issue(),
            "repository_path": "/tmp/example-project",
        },
        config=config,
    )
    snapshot = await graph.aget_state(config)

    assert result["status"] == "ready_for_plan_review"
    assert snapshot.values["status"] == "ready_for_plan_review"
    assert snapshot.next == ("plan_approval",)
