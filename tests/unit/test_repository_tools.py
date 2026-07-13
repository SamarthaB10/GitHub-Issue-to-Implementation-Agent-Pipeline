import json
import subprocess

from agents.tools.python_tools import build_python_tools
from agents.tools.repository_tools import build_repository_tools


def create_repository(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / "src" / "auth.py").write_text(
        '''"""Authentication services."""

from datetime import datetime


class AuthenticationService:
    async def login(self, username: str) -> bool:
        return bool(username)


def validate_token(token: str) -> bool:
    return bool(token)
''',
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_auth.py").write_text(
        "from src.auth import validate_token\n\n\ndef test_token():\n    assert validate_token('x')\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        '''[project]
name = "example"
requires-python = ">=3.11"
dependencies = ["fastapi>=0.100", "pytest>=8", "ruff>=0.5"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 88
''',
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")
    (tmp_path / ".github" / "workflows" / "test.yml").write_text(
        "name: test\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "init", "-q"],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


def tools_by_name(repository_path):
    tools = [
        *build_repository_tools(str(repository_path)),
        *build_python_tools(str(repository_path)),
    ]
    return {tool.name: tool for tool in tools}


def test_gather_repository_context_returns_structured_project_facts(tmp_path):
    repository = create_repository(tmp_path)
    tools = tools_by_name(repository)

    context = json.loads(tools["gather_repository_context"].invoke({}))

    assert context["file_count"] >= 5
    assert context["languages"]["Python"] == 2
    assert context["source_directory_candidates"] == ["src"]
    assert context["test_directory_candidates"] == ["tests"]
    assert "pyproject.toml" in context["manifests"]
    assert ".github/workflows/test.yml" in context["ci_files"]
    assert context["python"]["requires_python"] == ">=3.11"
    assert "pytest" in context["python"]["test_frameworks"]
    assert "ruff" in context["python"]["lint_tools"]
    assert context["python"]["pytest_paths"] == ["tests"]


def test_read_repository_files_reads_bounded_related_files(tmp_path):
    repository = create_repository(tmp_path)
    tool = tools_by_name(repository)["read_repository_files"]

    result = tool.invoke(
        {
            "relative_paths": ["src/auth.py", "tests/test_auth.py"],
            "max_lines_per_file": 20,
        }
    )

    assert "=== src/auth.py ===" in result
    assert "AuthenticationService" in result
    assert "=== tests/test_auth.py ===" in result
    assert "test_token" in result


def test_batch_read_rejects_too_many_files_and_path_escape(tmp_path):
    repository = create_repository(tmp_path)
    tools = tools_by_name(repository)

    too_many = tools["read_repository_files"].invoke(
        {"relative_paths": [f"file-{index}.py" for index in range(6)]}
    )
    escaped = tools["read_repository_file"].invoke(
        {"relative_path": "../secret.txt"}
    )

    assert "maximum of 5 files" in too_many
    assert "Path escapes the repository" in escaped


def test_inspect_python_file_returns_ast_structure_without_execution(tmp_path):
    repository = create_repository(tmp_path)
    tool = tools_by_name(repository)["inspect_python_file"]

    result = json.loads(tool.invoke({"relative_path": "src/auth.py"}))

    assert result["module_docstring"] == "Authentication services."
    assert "datetime.datetime" in result["imports"]
    assert result["classes"][0]["name"] == "AuthenticationService"
    assert result["classes"][0]["methods"][0]["name"] == "login"
    assert result["classes"][0]["methods"][0]["is_async"] is True
    assert result["functions"][0]["name"] == "validate_token"


def test_inspect_python_file_reports_syntax_errors(tmp_path):
    repository = create_repository(tmp_path)
    (repository / "src" / "broken.py").write_text(
        "def broken(:\n",
        encoding="utf-8",
    )
    tool = tools_by_name(repository)["inspect_python_file"]

    result = json.loads(tool.invoke({"relative_path": "src/broken.py"}))

    assert result["syntax_error"]["line"] == 1
