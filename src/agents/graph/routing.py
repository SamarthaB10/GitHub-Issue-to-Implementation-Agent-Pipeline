from typing import Literal

from agents.graph.state import AgentState


IssueAnalysisRoute = Literal["explore", "needs_clarification"]
ImplementationPlanRoute = Literal["review", "needs_clarification"]
PlanApprovalRoute = Literal["approve", "request_changes", "cancel"]


def route_after_issue_analysis(state: AgentState) -> IssueAnalysisRoute:
    """Route actionable issues to exploration and stop unclear issues."""

    issue_brief = state.get("issue_brief")

    if issue_brief is None:
        raise ValueError(
            "route_after_issue_analysis requires issue_brief in graph state."
        )

    if issue_brief.is_actionable:
        return "explore"

    return "needs_clarification"


def route_after_plan_approval(state: AgentState) -> PlanApprovalRoute:
    """Route the graph from the human's validated plan decision."""

    decision = state.get("plan_approval")

    if decision is None:
        raise ValueError(
            "route_after_plan_approval requires plan_approval in graph state."
        )

    return decision.action


def route_after_implementation_plan(state: AgentState) -> ImplementationPlanRoute:
    """Send complete plans to approval and stop plans with blocking questions."""

    implementation_plan = state.get("implementation_plan")

    if implementation_plan is None:
        raise ValueError(
            "route_after_implementation_plan requires implementation_plan "
            "in graph state."
        )

    if implementation_plan.ready_for_approval:
        return "review"

    return "needs_clarification"
