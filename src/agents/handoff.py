from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from schemas.approval import PlanApprovalDecision
from schemas.issue import IssueBrief, IssueInput
from schemas.planning import ImplementationPlan
from schemas.repository import RepositoryMap
from schemas.runtime import PlannerHandoff


def build_planner_handoff(
    state: Mapping[str, Any],
    *,
    base_commit: str,
    created_at: str | None = None,
) -> PlannerHandoff:
    """Export an approved LangGraph state as a validated Chief artifact."""

    required = ("issue", "issue_brief", "repository_map", "implementation_plan", "plan_approval")
    missing = [key for key in required if key not in state]
    if missing:
        raise ValueError(f"Planner state is missing: {', '.join(missing)}")
    issue = IssueInput.model_validate(state["issue"])
    approval = PlanApprovalDecision.model_validate(state["plan_approval"])
    return PlannerHandoff(
        run_id=str(state.get("run_id") or state.get("thread_id") or "planner-run"),
        repository=issue.repository,
        repository_path=str(state["repository_path"]),
        base_commit=base_commit,
        issue_brief=IssueBrief.model_validate(state["issue_brief"]),
        repository_map=RepositoryMap.model_validate(state["repository_map"]),
        implementation_plan=ImplementationPlan.model_validate(state["implementation_plan"]),
        plan_approval=approval,
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
    )
