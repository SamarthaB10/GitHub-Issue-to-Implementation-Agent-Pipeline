import base64
import json

import httpx
import pytest

from agents.tools.github_tools import (
    GitHubClient,
    GitHubToolError,
    build_github_exploration_tools,
)


def client_for(handler):
    return GitHubClient(
        repository="octo/example",
        client=httpx.Client(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ),
    )


def test_github_client_fetches_a_pinned_file_and_decodes_content():
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/repos/octo/example/contents/src/app.py"
        assert request.url.params["ref"] == "abc1234"
        return httpx.Response(
            200,
            json={
                "path": "src/app.py",
                "sha": "file-sha",
                "encoding": "base64",
                "content": base64.b64encode(b"one\ntwo\n").decode(),
            },
        )

    result = client_for(handler).fetch_file("src/app.py", ref="abc1234")

    assert result == {
        "path": "src/app.py",
        "sha": "file-sha",
        "ref": "abc1234",
        "content": "     1: one\n     2: two",
    }


def test_github_client_rejects_paths_that_escape_the_repository():
    client = client_for(lambda request: httpx.Response(200, json={}))

    with pytest.raises(GitHubToolError, match="relative path"):
        client.fetch_file("../secrets.txt")


def test_github_client_limits_search_results_and_never_uses_mutating_methods():
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/search/code"
        assert request.url.params["per_page"] == "2"
        return httpx.Response(200, json={"total_count": 3, "items": [{"path": "a"}, {"path": "b"}, {"path": "c"}]})

    result = client_for(handler).search_code("login", limit=2)

    assert result == {"total_count": 3, "items": [{"path": "a"}, {"path": "b"}]}


def test_github_langchain_tools_are_repository_scoped_and_read_only():
    def handler(request):
        assert request.method == "GET"
        return httpx.Response(200, json={"full_name": "octo/example"})

    tools = build_github_exploration_tools(
        "octo/example",
        client=GitHubClient(
            repository="octo/example",
            client=httpx.Client(
                base_url="https://api.github.test",
                transport=httpx.MockTransport(handler),
            ),
        ),
    )

    assert {tool.name for tool in tools} == {
        "github_repository_metadata",
        "github_fetch_file",
        "github_search_code",
        "github_fetch_issue",
        "github_search_issues",
        "github_fetch_issue_comments",
        "github_fetch_pull_request",
        "github_fetch_pull_request_patch",
        "github_fetch_pull_request_reviews",
        "github_fetch_pull_request_comments",
        "github_fetch_commit",
        "github_compare_commits",
        "github_fetch_commit_status",
        "github_fetch_rulesets",
        "github_fetch_branch_protection",
        "github_search_branches",
        "github_fetch_check_runs",
        "github_fetch_workflow_runs",
    }
    assert json.loads(tools[0].invoke({})) == {"full_name": "octo/example"}
