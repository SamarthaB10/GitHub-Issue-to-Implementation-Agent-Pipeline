import os

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from agents.graph.state import AgentState
from agents.shared import load_prompt
from agents.tools.github_tools import GitHubClient, build_github_exploration_tools
from agents.tools.python_tools import build_python_tools
from agents.tools.repository_tools import build_repository_tools
from schemas.repository import RepositoryMap

load_dotenv()


REPOSITORY_EXPLORER_SYSTEM_PROMPT = load_prompt(
    "repository_explorer/system.md"
)


REPOSITORY_EXPLORER_TASK_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "human",
            load_prompt("repository_explorer/human.md"),
        )
    ]
)


def build_repository_explorer(
    repository_path: str,
    *,
    github_repository: str | None = None,
    github_client: GitHubClient | None = None,
):
    """Build an explorer with local tools and optional scoped GitHub reads."""

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

    tools = [
        *build_repository_tools(repository_path),
        *build_python_tools(repository_path),
    ]
    if github_repository:
        tools.extend(
            build_github_exploration_tools(
                github_repository,
                client=github_client,
            )
        )

    return create_agent(
        model=model,
        tools=tools,
        system_prompt=REPOSITORY_EXPLORER_SYSTEM_PROMPT,
        response_format=RepositoryMap,
    )


async def repository_explorer_node(state: AgentState) -> dict:
    """Explore the repository and add a structured RepositoryMap to state."""

    issue_brief = state.get("issue_brief")

    if issue_brief is None:
        raise ValueError(
            "repository_explorer_node requires issue_brief in graph state."
        )

    if not issue_brief.is_actionable:
        raise ValueError(
            "Repository exploration cannot begin because the issue brief is "
            "not actionable."
        )

    task_messages = REPOSITORY_EXPLORER_TASK_PROMPT.format_messages(
        repository=state["issue"].repository,
        issue_brief=issue_brief.model_dump_json(indent=2),
    )
    explorer = build_repository_explorer(
        state["repository_path"],
        github_repository=state["issue"].repository,
    )
    result = await explorer.ainvoke(
        {"messages": task_messages},
        config={"recursion_limit": 30},
    )

    structured_response = result.get("structured_response")

    if structured_response is None:
        raise ValueError(
            "Repository explorer did not return a structured RepositoryMap."
        )

    repository_map = RepositoryMap.model_validate(structured_response)

    return {
        "repository_map": repository_map,
        "status": "repository_explored",
    }
