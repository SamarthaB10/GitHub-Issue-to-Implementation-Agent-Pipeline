import pytest
from pydantic import ValidationError

import agents.implementer as implementer_module
from schemas.issue import IssueBrief, IssueInput
from schemas.planning import ImplementationPlan, ImplementationStep, PlannedTest
from schemas.repository import RelevantFile, RepositoryMap


def make_state():
    issue = IssueInput(
        repository="example/project",
        number=42,
        title="Fix authentication failure",
        body="Valid users receive a server error when signing in.",
    )
    brief = IssueBrief(
        summary="Fix valid-user authentication.",
        problem_statement="Valid users cannot sign in.",
        requirements=["Restore authentication for valid users."],
        acceptance_criteria=["A valid user can sign in successfully."],
        in_scope=["Authentication failure handling."],
        out_of_scope=["Account registration."],
        is_actionable=True,
        actionability_reason="Expected behavior is clear.",
    )
    repository_map = RepositoryMap(
        summary="Authentication is implemented in the auth module.",
        relevant_files=[
            RelevantFile(
                path="src/auth.py",
                reason="Contains the login handler.",
            )
        ],
    )
    return {
        "issue": issue,
        "repository_path": "/tmp/example-project",
        "issue_brief": brief,
        "repository_map": repository_map,
    }


def make_plan(*, ready: bool) -> ImplementationPlan:
    return ImplementationPlan(
        summary="Correct authentication failure handling.",
        approach="Update the existing login handler.",
        steps=[
            ImplementationStep(
                order=1,
                description="Correct the valid-user login path.",
                affected_files=["src/auth.py"],
                rationale="Restores the required behavior.",
            )
        ],
        blocking_questions=[] if ready else ["Which error type is expected?"],
        ready_for_approval=ready,
    )


class FakePlannerChain:
    def __init__(self, response):
        self.response = response
        self.inputs = None

    async def ainvoke(self, inputs):
        self.inputs = inputs
        return self.response


def test_prompt_contains_issue_brief_and_repository_map():
    state = make_state()

    messages = implementer_module.IMPLEMENTATION_PLANNER_PROMPT.format_messages(
        issue_brief=state["issue_brief"].model_dump_json(indent=2),
        repository_map=state["repository_map"].model_dump_json(indent=2),
        previous_plan="No previous implementation plan exists.",
        plan_feedback="No human revision feedback was provided.",
    )

    assert len(messages) == 2
    assert "Fix valid-user authentication" in messages[1].content
    assert "src/auth.py" in messages[1].content


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_key", ["issue_brief", "repository_map"])
async def test_planner_requires_input_artifacts(missing_key):
    state = make_state()
    del state[missing_key]

    with pytest.raises(ValueError, match=f"requires {missing_key}"):
        await implementer_module.implementation_planner_node(state)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ready", "expected_status"),
    [
        (True, "ready_for_plan_review"),
        (False, "needs_clarification"),
    ],
)
async def test_planner_sets_status_from_plan(
    monkeypatch,
    ready,
    expected_status,
):
    fake_chain = FakePlannerChain(make_plan(ready=ready))
    monkeypatch.setattr(
        implementer_module,
        "build_implementation_planner_chain",
        lambda: fake_chain,
    )

    result = await implementer_module.implementation_planner_node(make_state())

    assert result["status"] == expected_status
    assert result["implementation_plan"].ready_for_approval is ready
    assert "src/auth.py" in fake_chain.inputs["repository_map"]


@pytest.mark.asyncio
async def test_planner_receives_previous_plan_and_human_feedback(monkeypatch):
    state = make_state()
    state["implementation_plan"] = make_plan(ready=True)
    state["plan_feedback"] = "Add an integration test step."
    fake_chain = FakePlannerChain(make_plan(ready=True))
    monkeypatch.setattr(
        implementer_module,
        "build_implementation_planner_chain",
        lambda: fake_chain,
    )

    await implementer_module.implementation_planner_node(state)

    assert "Correct authentication failure" in fake_chain.inputs["previous_plan"]
    assert fake_chain.inputs["plan_feedback"] == "Add an integration test step."


def test_planning_schema_rejects_extra_fields():
    plan_data = make_plan(ready=True).model_dump()
    plan_data["unexpected"] = "value"

    with pytest.raises(ValidationError, match="unexpected"):
        ImplementationPlan.model_validate(plan_data)


def test_planned_test_rejects_invalid_test_type():
    with pytest.raises(ValidationError, match="test_type"):
        PlannedTest(
            description="Verify login.",
            test_type="manual",
        )


def test_ready_plan_rejects_blocking_questions():
    plan_data = make_plan(ready=True).model_dump()
    plan_data["blocking_questions"] = ["Which error type is expected?"]

    with pytest.raises(ValidationError, match="blocking questions"):
        ImplementationPlan.model_validate(plan_data)
