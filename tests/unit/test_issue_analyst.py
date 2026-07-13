from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agents.issue_analyst import ISSUE_ANALYST_PROMPT
from schemas.issue import IssueBrief


def render_prompt():
    return ISSUE_ANALYST_PROMPT.format_messages(
        repository="example/project",
        issue_number=42,
        title="Login fails for valid users",
        body="Valid credentials return a server error.",
        labels="bug, agent-ready",
        comments="No comments were provided.",
    )


def test_few_shot_prompt_has_two_valid_input_output_examples():
    messages = render_prompt()

    assert len(messages) == 6
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    assert isinstance(messages[2], AIMessage)
    assert isinstance(messages[3], HumanMessage)
    assert isinstance(messages[4], AIMessage)
    assert isinstance(messages[5], HumanMessage)

    actionable_example = IssueBrief.model_validate_json(messages[2].content)
    ambiguous_example = IssueBrief.model_validate_json(messages[4].content)

    assert actionable_example.is_actionable is True
    assert actionable_example.acceptance_criteria
    assert ambiguous_example.is_actionable is False
    assert ambiguous_example.open_questions


def test_actual_issue_is_rendered_after_examples():
    messages = render_prompt()
    actual_issue = messages[-1].content

    assert "Repository: example/project" in actual_issue
    assert "Issue number: 42" in actual_issue
    assert "Login fails for valid users" in actual_issue
    assert "Valid credentials return a server error" in actual_issue
