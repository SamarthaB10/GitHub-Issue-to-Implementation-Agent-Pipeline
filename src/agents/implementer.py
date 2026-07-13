import os
from functools import lru_cache

from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from agents.graph.state import AgentState
from agents.shared import load_prompt
from schemas.planning import ImplementationPlan


load_dotenv()


IMPLEMENTATION_PLANNER_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            load_prompt("implementation_planner/system.md"),
        ),
        (
            "human",
            load_prompt("implementation_planner/human.md"),
        ),
    ]
)


@lru_cache(maxsize=1)
def build_implementation_planner_chain():
    """Build and cache the structured implementation-planning chain."""

    model_name = os.getenv("OPENAI_MODEL")

    if not model_name:
        raise RuntimeError(
            "OPENAI_MODEL is not configured. Add it to your .env file."
        )

    model = ChatOpenAI(
        model=model_name,
        temperature=0,
        timeout=60,
        max_retries=2,
    )

    return IMPLEMENTATION_PLANNER_PROMPT | model.with_structured_output(
        ImplementationPlan
    )


async def implementation_planner_node(state: AgentState) -> dict:
    """Create a structured implementation plan from approved graph artifacts."""

    issue_brief = state.get("issue_brief")

    if issue_brief is None:
        raise ValueError(
            "implementation_planner_node requires issue_brief in graph state."
        )

    repository_map = state.get("repository_map")

    if repository_map is None:
        raise ValueError(
            "implementation_planner_node requires repository_map in graph state."
        )

    planner_chain = build_implementation_planner_chain()
    structured_response = await planner_chain.ainvoke(
        {
            "issue_brief": issue_brief.model_dump_json(indent=2),
            "repository_map": repository_map.model_dump_json(indent=2),
            "previous_plan": (
                state["implementation_plan"].model_dump_json(indent=2)
                if state.get("implementation_plan")
                else "No previous implementation plan exists."
            ),
            "plan_feedback": state.get(
                "plan_feedback",
                "No human revision feedback was provided.",
            ),
        }
    )
    implementation_plan = ImplementationPlan.model_validate(structured_response)

    return {
        "implementation_plan": implementation_plan,
        "status": (
            "ready_for_plan_review"
            if implementation_plan.ready_for_approval
            else "needs_clarification"
        ),
    }
