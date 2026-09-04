import json
import os
from functools import lru_cache

from dotenv import load_dotenv
from langchain_core.prompts import (
    ChatPromptTemplate,
    FewShotChatMessagePromptTemplate,
)
from langchain_openai import ChatOpenAI

from agents.graph.state import AgentState
from agents.shared import load_prompt, load_prompt_examples
from schemas.issue import IssueBrief, IssueInput

load_dotenv()


ISSUE_ANALYST_EXAMPLES = [
    {
        "input": example["input"],
        "output": json.dumps(example["output"], indent=2),
    }
    for example in load_prompt_examples("issue_analyst/examples.json")
]


ISSUE_ANALYST_EXAMPLE_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("human", "{input}"),
        ("ai", "{output}"),
    ]
)


ISSUE_ANALYST_FEW_SHOT_PROMPT = FewShotChatMessagePromptTemplate(
    examples=ISSUE_ANALYST_EXAMPLES,
    example_prompt=ISSUE_ANALYST_EXAMPLE_PROMPT,
)


ISSUE_ANALYST_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", load_prompt("issue_analyst/system.md")),
        ISSUE_ANALYST_FEW_SHOT_PROMPT,
        ("human", load_prompt("issue_analyst/human.md")),
    ]
)


@lru_cache(maxsize=1)
def build_issue_analyst_chain():
    """Build and cache the structured issue-analysis chain."""

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

    return ISSUE_ANALYST_PROMPT | model.with_structured_output(IssueBrief)


def format_issue_comments(issue: IssueInput) -> str:
    """Format issue comments for the human prompt message."""

    if not issue.comments:
        return "No comments were provided."

    return "\n\n".join(
        f"Comment by {comment.author}:\n{comment.body}"
        for comment in issue.comments
    )


async def issue_analyst_node(state: AgentState) -> dict:
    """Analyze the raw issue and add a validated IssueBrief to graph state."""

    issue = state["issue"]
    analyst_chain = build_issue_analyst_chain()

    brief = await analyst_chain.ainvoke(
        {
            "repository": issue.repository,
            "issue_number": issue.number,
            "title": issue.title,
            "body": issue.body or "No issue body was provided.",
            "labels": ", ".join(issue.labels) or "No labels were provided.",
            "comments": format_issue_comments(issue),
        }
    )

    return {
        "issue_brief": brief,
        "status": (
            "ready_for_exploration"
            if brief.is_actionable
            else "needs_clarification"
        ),
    }
