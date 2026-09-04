"""Bounded, read-only GitHub tools for Planner agents."""

import base64
import json
import os
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote

import httpx
from langchain.tools import tool

MAX_GITHUB_ITEMS = 100
MAX_GITHUB_RESPONSE_BYTES = 1_000_000
MAX_GITHUB_FILE_BYTES = 500_000
DEFAULT_TIMEOUT_SECONDS = 15.0


class GitHubToolError(RuntimeError):
    """Raised when a bounded GitHub read cannot be completed."""


def _repository_parts(repository: str) -> tuple[str, str]:
    parts = repository.strip().split("/")
    if len(parts) != 2 or any(not part or part in {".", ".."} for part in parts):
        raise GitHubToolError("repository must use owner/name format.")
    return parts[0], parts[1]


def _relative_file_path(path: str) -> str:
    if not isinstance(path, str) or not path.strip():
        raise GitHubToolError("file path must be a non-empty relative path.")
    candidate = PurePosixPath(path.strip())
    if candidate.is_absolute() or ".." in candidate.parts:
        raise GitHubToolError("file path must be a relative path without escapes.")
    if ".git" in candidate.parts:
        raise GitHubToolError(".git is not available through the GitHub tool.")
    return candidate.as_posix()


def _bounded_items(payload: Any, limit: int) -> Any:
    if isinstance(payload, dict):
        bounded = dict(payload)
        for key in ("items", "files", "commits", "workflow_runs", "check_runs"):
            value = bounded.get(key)
            if isinstance(value, list):
                bounded[key] = value[:limit]
        return bounded
    if isinstance(payload, list):
        return payload[:limit]
    return payload


class GitHubClient:
    """Perform only bounded GET requests for one GitHub repository."""

    def __init__(
        self,
        repository: str,
        *,
        token: str | None = None,
        base_url: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.owner, self.name = _repository_parts(repository)
        self.repository = f"{self.owner}/{self.name}"
        self._client = client or httpx.Client(
            base_url=(base_url or os.getenv("GITHUB_API_URL") or "https://api.github.com").rstrip("/"),
            timeout=timeout,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        self._owns_client = client is None
        credential = token if token is not None else os.getenv("GITHUB_TOKEN")
        if credential:
            self._client.headers["Authorization"] = f"Bearer {credential}"

    @classmethod
    def from_environment(cls, repository: str) -> "GitHubClient":
        """Build a client without requiring a credential for public reads."""

        return cls(repository)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def repository_metadata(self) -> dict[str, Any]:
        return self._get(f"/repos/{self.repository}")

    def fetch_directory(self, path: str = "", *, ref: str | None = None) -> Any:
        clean_path = _relative_file_path(path) if path else ""
        endpoint = f"/repos/{self.repository}/contents/{quote(clean_path, safe='/')}"
        return self._get(endpoint, params={"ref": ref} if ref else None)

    def fetch_file(
        self,
        path: str,
        *,
        ref: str | None = None,
        start_line: int = 1,
        end_line: int = 400,
    ) -> dict[str, Any]:
        if start_line < 1 or end_line < start_line or end_line - start_line + 1 > 400:
            raise GitHubToolError("file line range must contain 1 to 400 lines.")
        payload = self.fetch_directory(path, ref=ref)
        if not isinstance(payload, dict) or payload.get("type") not in {None, "file"}:
            raise GitHubToolError("GitHub path is not a file.")
        encoded = payload.get("content", "")
        if payload.get("encoding") == "base64":
            try:
                raw = base64.b64decode(str(encoded), validate=False)
            except ValueError as exc:
                raise GitHubToolError("GitHub returned invalid base64 content.") from exc
        else:
            raw = str(encoded).encode("utf-8")
        if len(raw) > MAX_GITHUB_FILE_BYTES:
            raise GitHubToolError("GitHub file is too large for Planner tools.")
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        selected = "\n".join(
            f"{number:>6}: {line}"
            for number, line in enumerate(lines[start_line - 1 : end_line], start=start_line)
        )
        return {
            "path": path,
            "sha": payload.get("sha"),
            "ref": ref,
            "content": selected,
        }

    def search_code(self, query: str, *, ref: str | None = None, limit: int = 20) -> dict[str, Any]:
        if not query.strip():
            raise GitHubToolError("code search query cannot be empty.")
        bounded_limit = max(1, min(limit, MAX_GITHUB_ITEMS))
        scoped_query = f"{query} repo:{self.repository}"
        params: dict[str, Any] = {
            "q": scoped_query,
            "per_page": bounded_limit,
        }
        if ref:
            params["ref"] = ref
        payload = self._get(
            "/search/code",
            params=params,
        )
        return _bounded_items(payload, bounded_limit)

    def fetch_issue(self, number: int, *, include_comments: bool = True) -> dict[str, Any]:
        if number < 1:
            raise GitHubToolError("issue number must be positive.")
        issue = self._get(f"/repos/{self.repository}/issues/{number}")
        if include_comments:
            issue["comments_data"] = self._get(
                f"/repos/{self.repository}/issues/{number}/comments",
                params={"per_page": MAX_GITHUB_ITEMS},
            )
        return issue

    def search_issues(self, query: str, *, limit: int = 20) -> dict[str, Any]:
        if not query.strip():
            raise GitHubToolError("issue search query cannot be empty.")
        bounded_limit = max(1, min(limit, MAX_GITHUB_ITEMS))
        return _bounded_items(
            self._get(
                "/search/issues",
                params={
                    "q": f"{query} repo:{self.repository}",
                    "per_page": bounded_limit,
                },
            ),
            bounded_limit,
        )

    def fetch_issue_comments(self, number: int) -> list[Any]:
        if number < 1:
            raise GitHubToolError("issue number must be positive.")
        return _bounded_items(
            self._get(
                f"/repos/{self.repository}/issues/{number}/comments",
                params={"per_page": MAX_GITHUB_ITEMS},
            ),
            MAX_GITHUB_ITEMS,
        )

    def fetch_pull_request(self, number: int, *, include_files: bool = True) -> dict[str, Any]:
        if number < 1:
            raise GitHubToolError("pull request number must be positive.")
        pull_request = self._get(f"/repos/{self.repository}/pulls/{number}")
        if include_files:
            pull_request["files"] = self._get(
                f"/repos/{self.repository}/pulls/{number}/files",
                params={"per_page": MAX_GITHUB_ITEMS},
            )
        return pull_request

    def fetch_pull_request_patch(self, number: int) -> str:
        if number < 1:
            raise GitHubToolError("pull request number must be positive.")
        return self._get_text(
            f"/repos/{self.repository}/pulls/{number}.diff",
            accept="application/vnd.github.diff",
        )

    def fetch_pull_request_reviews(self, number: int) -> list[Any]:
        if number < 1:
            raise GitHubToolError("pull request number must be positive.")
        return _bounded_items(
            self._get(
                f"/repos/{self.repository}/pulls/{number}/reviews",
                params={"per_page": MAX_GITHUB_ITEMS},
            ),
            MAX_GITHUB_ITEMS,
        )

    def fetch_pull_request_comments(self, number: int) -> list[Any]:
        if number < 1:
            raise GitHubToolError("pull request number must be positive.")
        return _bounded_items(
            self._get(
                f"/repos/{self.repository}/pulls/{number}/comments",
                params={"per_page": MAX_GITHUB_ITEMS},
            ),
            MAX_GITHUB_ITEMS,
        )

    def fetch_commit(self, sha: str) -> dict[str, Any]:
        if not sha.strip() or "/" in sha:
            raise GitHubToolError("commit reference is invalid.")
        return self._get(f"/repos/{self.repository}/commits/{quote(sha, safe='')}")

    def compare_commits(self, base: str, head: str) -> dict[str, Any]:
        if not base.strip() or not head.strip():
            raise GitHubToolError("both commit references are required.")
        return _bounded_items(
            self._get(
                f"/repos/{self.repository}/compare/{quote(base, safe='')}...{quote(head, safe='')}"
            ),
            MAX_GITHUB_ITEMS,
        )

    def fetch_commit_status(self, sha: str) -> dict[str, Any]:
        return _bounded_items(
            self._get(f"/repos/{self.repository}/commits/{quote(sha, safe='')}/status"),
            MAX_GITHUB_ITEMS,
        )

    def fetch_rulesets(self) -> list[Any]:
        return _bounded_items(
            self._get(f"/repos/{self.repository}/rulesets", params={"per_page": MAX_GITHUB_ITEMS}),
            MAX_GITHUB_ITEMS,
        )

    def fetch_branch_protection(self, branch: str) -> dict[str, Any]:
        if not branch.strip():
            raise GitHubToolError("branch name cannot be empty.")
        return self._get(
            f"/repos/{self.repository}/branches/{quote(branch, safe='')}/protection"
        )

    def search_branches(self, query: str = "", *, limit: int = 20) -> dict[str, Any]:
        bounded_limit = max(1, min(limit, MAX_GITHUB_ITEMS))
        branches = self._get(
            f"/repos/{self.repository}/branches",
            params={"per_page": bounded_limit},
        )
        if query:
            branches = [
                branch for branch in branches
                if query.lower() in str(branch.get("name", "")).lower()
            ]
        return {"items": _bounded_items(branches, bounded_limit)}

    def fetch_check_runs(self, ref: str, *, limit: int = 20) -> dict[str, Any]:
        bounded_limit = max(1, min(limit, MAX_GITHUB_ITEMS))
        return _bounded_items(
            self._get(
                f"/repos/{self.repository}/commits/{quote(ref, safe='')}/check-runs",
                params={"per_page": bounded_limit},
            ),
            bounded_limit,
        )

    def fetch_workflow_runs(self, *, branch: str | None = None, limit: int = 20) -> dict[str, Any]:
        bounded_limit = max(1, min(limit, MAX_GITHUB_ITEMS))
        params: dict[str, Any] = {"per_page": bounded_limit}
        if branch:
            params["branch"] = branch
        return _bounded_items(
            self._get(f"/repos/{self.repository}/actions/runs", params=params),
            bounded_limit,
        )

    def _get(
        self,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        try:
            response = self._client.get(endpoint, params=params)
        except httpx.HTTPError as exc:
            raise GitHubToolError(f"GitHub read failed: {exc}") from exc
        if len(response.content) > MAX_GITHUB_RESPONSE_BYTES:
            raise GitHubToolError("GitHub response is too large for Planner tools.")
        if response.status_code >= 400:
            if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
                raise GitHubToolError("GitHub rate limit is exhausted; retry later.")
            raise GitHubToolError(
                f"GitHub read returned HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise GitHubToolError("GitHub returned invalid JSON.") from exc
        return payload

    def _get_text(self, endpoint: str, *, accept: str) -> str:
        try:
            response = self._client.get(endpoint, headers={"Accept": accept})
        except httpx.HTTPError as exc:
            raise GitHubToolError(f"GitHub read failed: {exc}") from exc
        if len(response.content) > MAX_GITHUB_RESPONSE_BYTES:
            raise GitHubToolError("GitHub response is too large for Planner tools.")
        if response.status_code >= 400:
            raise GitHubToolError(
                f"GitHub read returned HTTP {response.status_code}: {response.text[:500]}"
            )
        return response.text


def build_github_exploration_tools(
    repository: str,
    *,
    client: GitHubClient | None = None,
):
    """Build the fixed read-only GitHub tool set for one Planner."""

    github = client or GitHubClient.from_environment(repository)

    @tool
    def github_repository_metadata() -> str:
        """Read metadata for the scoped repository."""

        return json.dumps(github.repository_metadata(), sort_keys=True)

    @tool
    def github_fetch_file(path: str, ref: str | None = None, start_line: int = 1, end_line: int = 400) -> str:
        """Read a bounded file at an optional Git ref."""

        return json.dumps(
            github.fetch_file(path, ref=ref, start_line=start_line, end_line=end_line),
            sort_keys=True,
        )

    @tool
    def github_search_code(query: str, ref: str | None = None, limit: int = 20) -> str:
        """Search code inside the scoped repository."""

        return json.dumps(github.search_code(query, ref=ref, limit=limit), sort_keys=True)

    @tool
    def github_fetch_issue(number: int, include_comments: bool = True) -> str:
        """Read one issue and bounded comments."""

        return json.dumps(github.fetch_issue(number, include_comments=include_comments), sort_keys=True)

    @tool
    def github_search_issues(query: str, limit: int = 20) -> str:
        """Search issues inside the scoped repository."""

        return json.dumps(github.search_issues(query, limit=limit), sort_keys=True)

    @tool
    def github_fetch_issue_comments(number: int) -> str:
        """Read bounded comments for one issue."""

        return json.dumps(github.fetch_issue_comments(number), sort_keys=True)

    @tool
    def github_fetch_pull_request(number: int, include_files: bool = True) -> str:
        """Read one pull request and bounded changed files."""

        return json.dumps(github.fetch_pull_request(number, include_files=include_files), sort_keys=True)

    @tool
    def github_fetch_pull_request_patch(number: int) -> str:
        """Read one pull request diff without changing the pull request."""

        return github.fetch_pull_request_patch(number)

    @tool
    def github_fetch_pull_request_reviews(number: int) -> str:
        """Read bounded pull request reviews."""

        return json.dumps(github.fetch_pull_request_reviews(number), sort_keys=True)

    @tool
    def github_fetch_pull_request_comments(number: int) -> str:
        """Read bounded pull request review comments."""

        return json.dumps(github.fetch_pull_request_comments(number), sort_keys=True)

    @tool
    def github_fetch_commit(sha: str) -> str:
        """Read one commit and its bounded GitHub metadata."""

        return json.dumps(github.fetch_commit(sha), sort_keys=True)

    @tool
    def github_compare_commits(base: str, head: str) -> str:
        """Compare two commits in the scoped repository."""

        return json.dumps(github.compare_commits(base, head), sort_keys=True)

    @tool
    def github_fetch_commit_status(sha: str) -> str:
        """Read commit status contexts."""

        return json.dumps(github.fetch_commit_status(sha), sort_keys=True)

    @tool
    def github_fetch_rulesets() -> str:
        """Read repository rulesets."""

        return json.dumps(github.fetch_rulesets(), sort_keys=True)

    @tool
    def github_fetch_branch_protection(branch: str) -> str:
        """Read branch protection settings."""

        return json.dumps(github.fetch_branch_protection(branch), sort_keys=True)

    @tool
    def github_search_branches(query: str = "", limit: int = 20) -> str:
        """Read and filter repository branches."""

        return json.dumps(github.search_branches(query, limit=limit), sort_keys=True)

    @tool
    def github_fetch_check_runs(ref: str, limit: int = 20) -> str:
        """Read check runs for a commit or ref."""

        return json.dumps(github.fetch_check_runs(ref, limit=limit), sort_keys=True)

    @tool
    def github_fetch_workflow_runs(branch: str | None = None, limit: int = 20) -> str:
        """Read recent workflow runs for the scoped repository."""

        return json.dumps(github.fetch_workflow_runs(branch=branch, limit=limit), sort_keys=True)

    return [
        github_repository_metadata,
        github_fetch_file,
        github_search_code,
        github_fetch_issue,
        github_search_issues,
        github_fetch_issue_comments,
        github_fetch_pull_request,
        github_fetch_pull_request_patch,
        github_fetch_pull_request_reviews,
        github_fetch_pull_request_comments,
        github_fetch_commit,
        github_compare_commits,
        github_fetch_commit_status,
        github_fetch_rulesets,
        github_fetch_branch_protection,
        github_search_branches,
        github_fetch_check_runs,
        github_fetch_workflow_runs,
    ]
