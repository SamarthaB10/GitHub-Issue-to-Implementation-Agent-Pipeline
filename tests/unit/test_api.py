import pytest
from fastapi.testclient import TestClient

import agents.graph.workflow as workflow_module
from api.app import create_app
from api.service import RunService
from schemas.issue import IssueBrief
from schemas.planning import ImplementationPlan, ImplementationStep
from schemas.repository import RelevantFile, RepositoryMap


def make_brief() -> IssueBrief:
    return IssueBrief(
        summary="Fix valid-user authentication.",
        problem_statement="Valid users cannot sign in.",
        requirements=["Restore authentication for valid users."],
        acceptance_criteria=["A valid user can sign in successfully."],
        in_scope=["Authentication failure handling."],
        out_of_scope=["Account registration."],
        is_actionable=True,
        actionability_reason="Expected behavior is clear.",
    )


def make_repository_map() -> RepositoryMap:
    return RepositoryMap(
        summary="Authentication is implemented in the auth module.",
        relevant_files=[
            RelevantFile(
                path="src/auth.py",
                reason="Contains the login handler.",
            )
        ],
    )


def make_plan() -> ImplementationPlan:
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
        ready_for_approval=True,
    )


@pytest.fixture
def client(monkeypatch):
    async def fake_issue_analyst(state):
        return {
            "issue_brief": make_brief(),
            "status": "ready_for_exploration",
        }

    async def fake_repository_explorer(state):
        return {
            "repository_map": make_repository_map(),
            "status": "repository_explored",
        }

    async def fake_implementation_planner(state):
        return {
            "implementation_plan": make_plan(),
            "status": "ready_for_plan_review",
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

    graph = workflow_module.build_workflow()
    app = create_app(RunService(graph))

    with TestClient(app) as test_client:
        yield test_client


def make_start_payload(repository_path: str) -> dict:
    return {
        "issue": {
            "repository": "example/project",
            "number": 42,
            "title": "Fix authentication failure",
            "body": "Valid users receive a server error when signing in.",
            "labels": ["bug", "agent-ready"],
        },
        "repository_path": repository_path,
    }


def start_run(client: TestClient, repository_path: str) -> dict:
    response = client.post(
        "/api/runs",
        json=make_start_payload(repository_path),
    )
    assert response.status_code == 201
    return response.json()


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_start_and_get_paused_run(client, tmp_path):
    started = start_run(client, str(tmp_path))

    assert started["thread_id"]
    assert started["status"] == "ready_for_plan_review"
    assert started["pending_nodes"] == ["plan_approval"]
    assert started["interrupt"]["type"] == "plan_approval"
    assert started["completed"] is False

    response = client.get(f"/api/runs/{started['thread_id']}")

    assert response.status_code == 200
    assert response.json() == started


def test_approve_run(client, tmp_path):
    started = start_run(client, str(tmp_path))

    response = client.post(
        f"/api/runs/{started['thread_id']}/decision",
        json={"action": "approve"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "plan_approved"
    assert result["state"]["plan_approval"]["action"] == "approve"
    assert result["pending_nodes"] == []
    assert result["interrupt"] is None
    assert result["completed"] is True


def test_completed_run_rejects_another_decision(client, tmp_path):
    started = start_run(client, str(tmp_path))
    decision_url = f"/api/runs/{started['thread_id']}/decision"
    assert client.post(decision_url, json={"action": "approve"}).status_code == 200

    response = client.post(decision_url, json={"action": "approve"})

    assert response.status_code == 409
    assert "not waiting" in response.json()["detail"]


def test_unknown_run_returns_not_found(client):
    response = client.get("/api/runs/unknown-thread")

    assert response.status_code == 404


def test_change_request_requires_feedback(client, tmp_path):
    started = start_run(client, str(tmp_path))

    response = client.post(
        f"/api/runs/{started['thread_id']}/decision",
        json={"action": "request_changes"},
    )

    assert response.status_code == 422


def test_start_requires_absolute_existing_repository(client):
    response = client.post(
        "/api/runs",
        json=make_start_payload("relative/repository"),
    )

    assert response.status_code == 422
