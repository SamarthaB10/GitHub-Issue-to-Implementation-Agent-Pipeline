from pydantic import ValidationError
from langgraph.types import interrupt

from agents.graph.state import AgentState
from schemas.approval import PlanApprovalDecision


def plan_approval_node(state: AgentState) -> dict:
    """Pause the workflow until a human reviews the implementation plan."""

    implementation_plan = state.get("implementation_plan")

    if implementation_plan is None:
        raise ValueError(
            "plan_approval_node requires implementation_plan in graph state."
        )

    payload = {
        "type": "plan_approval",
        "question": "Approve this implementation plan?",
        "implementation_plan": implementation_plan.model_dump(mode="json"),
        "allowed_actions": ["approve", "request_changes", "cancel"],
    }

    while True:
        raw_decision = interrupt(payload)

        try:
            decision = PlanApprovalDecision.model_validate(raw_decision)
            break
        except ValidationError as exc:
            payload = {
                **payload,
                "validation_error": str(exc),
            }

    status_by_action = {
        "approve": "plan_approved",
        "request_changes": "plan_revision_requested",
        "cancel": "cancelled",
    }
    update = {
        "plan_approval": decision,
        "status": status_by_action[decision.action],
    }

    if decision.feedback:
        update["plan_feedback"] = decision.feedback.strip()

    return update
