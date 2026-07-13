from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from agents.graph.approvals import plan_approval_node
from agents.graph.routing import (
    route_after_implementation_plan,
    route_after_issue_analysis,
    route_after_plan_approval,
)
from agents.graph.state import AgentState
from agents.implementer import implementation_planner_node
from agents.issue_analyst import issue_analyst_node
from agents.repo_explorer import repository_explorer_node


def build_workflow(checkpointer=None):
    """Build the issue-analysis, exploration, and planning workflow."""

    builder = StateGraph(AgentState)

    builder.add_node("issue_analyst", issue_analyst_node)
    builder.add_node("repository_explorer", repository_explorer_node)
    builder.add_node("implementation_planner", implementation_planner_node)
    builder.add_node("plan_approval", plan_approval_node)

    builder.add_edge(START, "issue_analyst")
    builder.add_conditional_edges(
        "issue_analyst",
        route_after_issue_analysis,
        {
            "explore": "repository_explorer",
            "needs_clarification": END,
        },
    )
    builder.add_edge("repository_explorer", "implementation_planner")
    builder.add_conditional_edges(
        "implementation_planner",
        route_after_implementation_plan,
        {
            "review": "plan_approval",
            "needs_clarification": END,
        },
    )
    builder.add_conditional_edges(
        "plan_approval",
        route_after_plan_approval,
        {
            "approve": END,
            "request_changes": "implementation_planner",
            "cancel": END,
        },
    )

    effective_checkpointer = (
        checkpointer if checkpointer is not None else InMemorySaver()
    )
    return builder.compile(checkpointer=effective_checkpointer)
