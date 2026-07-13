import pytest

from agents.shared import load_prompt, load_prompt_examples


@pytest.mark.parametrize(
    "relative_path",
    [
        "issue_analyst/system.md",
        "issue_analyst/human.md",
        "repository_explorer/system.md",
        "repository_explorer/human.md",
        "implementation_planner/system.md",
        "implementation_planner/human.md",
    ],
)
def test_agent_prompt_files_load(relative_path):
    assert load_prompt(relative_path)


def test_issue_analyst_examples_load_as_structured_json():
    examples = load_prompt_examples("issue_analyst/examples.json")

    assert len(examples) == 2
    assert examples[0]["output"]["is_actionable"] is True
    assert examples[1]["output"]["is_actionable"] is False


@pytest.mark.parametrize("relative_path", ["../secret.md", "/tmp/secret.md"])
def test_prompt_loader_rejects_paths_outside_prompt_folder(relative_path):
    with pytest.raises(ValueError, match="Prompt path"):
        load_prompt(relative_path)


def test_repository_explorer_prompt_requires_initial_context_gathering():
    prompt = load_prompt("repository_explorer/system.md")

    assert "Begin with gather_repository_context" in prompt
    assert "inspect_python_file" in prompt
