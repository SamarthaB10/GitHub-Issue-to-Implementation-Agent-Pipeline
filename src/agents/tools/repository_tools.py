import json
import subprocess
import tomllib
from collections import Counter
from pathlib import Path

from langchain.tools import tool


MAX_COMMAND_OUTPUT = 12_000
MAX_LISTED_FILES = 500
MAX_CONTEXT_FILES = 5_000
MAX_SEARCH_RESULTS = 200
MAX_READ_LINES = 400
MAX_BATCH_FILES = 5
MAX_BATCH_LINES_PER_FILE = 200
MAX_FILE_SIZE_BYTES = 1_000_000

LANGUAGE_BY_SUFFIX = {
    ".c": "C",
    ".cpp": "C++",
    ".cs": "C#",
    ".css": "CSS",
    ".go": "Go",
    ".html": "HTML",
    ".java": "Java",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".kt": "Kotlin",
    ".php": "PHP",
    ".py": "Python",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".scala": "Scala",
    ".sh": "Shell",
    ".sql": "SQL",
    ".swift": "Swift",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".vue": "Vue",
    ".yml": "YAML",
    ".yaml": "YAML",
}

MANIFEST_NAMES = {
    "Cargo.toml",
    "Gemfile",
    "go.mod",
    "package.json",
    "pom.xml",
    "pyproject.toml",
    "requirements.txt",
    "setup.cfg",
    "setup.py",
}

LOCKFILE_NAMES = {
    "Cargo.lock",
    "Gemfile.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "yarn.lock",
}


def _truncate_lines(text: str, *, max_lines: int, max_chars: int) -> str:
    lines = text.splitlines()
    truncated = len(lines) > max_lines or len(text) > max_chars
    output = "\n".join(lines[:max_lines])[:max_chars]

    if truncated:
        output += "\n... output truncated ..."

    return output


def _resolve_repository_file(
    repository_root: Path,
    relative_path: str,
) -> Path:
    """Resolve a model-provided path while keeping it inside the repository."""

    requested_path = Path(relative_path)

    if requested_path.is_absolute():
        raise ValueError("Absolute paths are not allowed.")

    resolved_path = (repository_root / requested_path).resolve()

    try:
        repository_relative_path = resolved_path.relative_to(repository_root)
    except ValueError as exc:
        raise ValueError("Path escapes the repository.") from exc

    if ".git" in repository_relative_path.parts:
        raise ValueError("Access to .git is not allowed.")

    return resolved_path


def _run_read_only_command(
    command: list[str],
    *,
    repository_root: Path,
    timeout: int = 10,
) -> subprocess.CompletedProcess[str] | None:
    """Run a fixed read-only command without invoking a shell."""

    try:
        return subprocess.run(
            command,
            cwd=repository_root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _read_repository_file_range(
    repository_root: Path,
    relative_path: str,
    *,
    start_line: int,
    end_line: int,
) -> str:
    if not relative_path.strip():
        return "File path cannot be empty."

    if start_line < 1:
        return "start_line must be at least 1."

    if end_line < start_line:
        return "end_line must be greater than or equal to start_line."

    if end_line - start_line + 1 > MAX_READ_LINES:
        return f"A maximum of {MAX_READ_LINES} lines can be read at once."

    try:
        file_path = _resolve_repository_file(
            repository_root,
            relative_path.strip(),
        )
    except ValueError as exc:
        return f"File access rejected: {exc}"

    if not file_path.is_file():
        return f"File does not exist: {relative_path}"

    if file_path.stat().st_size > MAX_FILE_SIZE_BYTES:
        return "File is too large to read with this tool."

    raw_content = file_path.read_bytes()

    if b"\x00" in raw_content:
        return "Binary files cannot be read with this tool."

    lines = raw_content.decode("utf-8", errors="replace").splitlines()
    selected_lines = lines[start_line - 1 : end_line]

    if not selected_lines:
        return (
            f"No content in requested range. "
            f"The file contains {len(lines)} lines."
        )

    numbered_lines = [
        f"{line_number:>6}: {line}"
        for line_number, line in enumerate(selected_lines, start=start_line)
    ]

    return _truncate_lines(
        "\n".join(numbered_lines),
        max_lines=MAX_READ_LINES,
        max_chars=MAX_COMMAND_OUTPUT,
    )


def _list_repository_paths(repository_root: Path) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    result = _run_read_only_command(
        ["rg", "--files", "--hidden", "--glob", "!.git/**"],
        repository_root=repository_root,
    )

    if result is None:
        return [], ["File discovery failed because rg was unavailable or timed out."]

    if result.returncode not in (0, 1):
        return [], [f"File discovery failed: {result.stderr[:500]}"]

    paths = [line for line in result.stdout.splitlines() if line]

    if len(paths) > MAX_CONTEXT_FILES:
        warnings.append(
            f"Repository context was limited to the first {MAX_CONTEXT_FILES} files."
        )
        paths = paths[:MAX_CONTEXT_FILES]

    return paths, warnings


def _parse_python_project(
    repository_root: Path,
    repository_paths: set[str],
    warnings: list[str],
) -> dict:
    python_context: dict = {
        "requires_python": None,
        "dependencies": [],
        "optional_dependency_groups": [],
        "test_frameworks": [],
        "lint_tools": [],
        "pytest_paths": [],
    }
    dependencies: list[str] = []

    if "pyproject.toml" in repository_paths:
        try:
            pyproject = tomllib.loads(
                (repository_root / "pyproject.toml").read_text(encoding="utf-8")
            )
            project = pyproject.get("project", {})
            tool = pyproject.get("tool", {})
            dependencies.extend(project.get("dependencies", []))
            python_context["requires_python"] = project.get("requires-python")
            python_context["optional_dependency_groups"] = sorted(
                project.get("optional-dependencies", {}).keys()
            )

            pytest_config = tool.get("pytest", {}).get("ini_options", {})
            testpaths = pytest_config.get("testpaths", [])
            if isinstance(testpaths, str):
                testpaths = [testpaths]
            python_context["pytest_paths"] = testpaths

            if "pytest" in tool or any(
                "pytest" in dependency.lower() for dependency in dependencies
            ):
                python_context["test_frameworks"].append("pytest")
            if "ruff" in tool or any(
                dependency.lower().startswith("ruff") for dependency in dependencies
            ):
                python_context["lint_tools"].append("ruff")
        except (OSError, tomllib.TOMLDecodeError) as exc:
            warnings.append(f"Could not parse pyproject.toml: {exc}")

    if "requirements.txt" in repository_paths:
        try:
            requirement_lines = (
                (repository_root / "requirements.txt")
                .read_text(encoding="utf-8", errors="replace")
                .splitlines()
            )
            dependencies.extend(
                line.strip()
                for line in requirement_lines
                if line.strip() and not line.lstrip().startswith(("#", "-"))
            )
        except OSError as exc:
            warnings.append(f"Could not read requirements.txt: {exc}")

    if "pytest.ini" in repository_paths and "pytest" not in python_context["test_frameworks"]:
        python_context["test_frameworks"].append("pytest")

    if "ruff.toml" in repository_paths and "ruff" not in python_context["lint_tools"]:
        python_context["lint_tools"].append("ruff")

    unique_dependencies = list(dict.fromkeys(dependencies))[:200]
    normalized_dependencies = [dependency.lower() for dependency in unique_dependencies]

    if any("pytest" in dependency for dependency in normalized_dependencies):
        if "pytest" not in python_context["test_frameworks"]:
            python_context["test_frameworks"].append("pytest")

    if any(dependency.startswith("ruff") for dependency in normalized_dependencies):
        if "ruff" not in python_context["lint_tools"]:
            python_context["lint_tools"].append("ruff")

    python_context["dependencies"] = unique_dependencies
    return python_context


def build_repository_tools(repository_path: str):
    """Create generic read-only tools confined to one approved repository root."""

    repository_root = Path(repository_path).expanduser().resolve()

    if not repository_root.is_dir():
        raise ValueError(f"Repository does not exist: {repository_root}")

    @tool
    def gather_repository_context() -> str:
        """Gather a bounded structural overview of the repository before targeted exploration."""

        repository_paths, warnings = _list_repository_paths(repository_root)
        path_set = set(repository_paths)
        suffix_counts = Counter(
            Path(path).suffix.lower()
            for path in repository_paths
            if Path(path).suffix
        )
        language_counts = Counter()

        for suffix, count in suffix_counts.items():
            language = LANGUAGE_BY_SUFFIX.get(suffix)
            if language:
                language_counts[language] += count

        top_level_directories = sorted(
            {
                Path(path).parts[0]
                for path in repository_paths
                if len(Path(path).parts) > 1
            }
        )
        source_candidates = [
            directory
            for directory in ("app", "lib", "packages", "src")
            if directory in top_level_directories
        ]
        test_candidates = [
            directory
            for directory in ("spec", "specs", "test", "tests")
            if directory in top_level_directories
        ]
        manifests = sorted(
            path for path in repository_paths if Path(path).name in MANIFEST_NAMES
        )
        lockfiles = sorted(
            path for path in repository_paths if Path(path).name in LOCKFILE_NAMES
        )
        ci_files = sorted(
            path
            for path in repository_paths
            if path.startswith(".github/workflows/")
            or path in {".circleci/config.yml", ".gitlab-ci.yml", "Jenkinsfile"}
        )
        documentation = sorted(
            path
            for path in repository_paths
            if Path(path).name.lower().startswith(("readme", "contributing"))
            or path.startswith("docs/")
        )[:100]

        branch = None
        is_dirty = None
        branch_result = _run_read_only_command(
            ["git", "branch", "--show-current"],
            repository_root=repository_root,
        )
        status_result = _run_read_only_command(
            ["git", "status", "--porcelain"],
            repository_root=repository_root,
        )

        if branch_result and branch_result.returncode == 0:
            branch = branch_result.stdout.strip() or None
        else:
            warnings.append("Git branch information is unavailable.")

        if status_result and status_result.returncode == 0:
            is_dirty = bool(status_result.stdout.strip())
        else:
            warnings.append("Git working-tree status is unavailable.")

        context = {
            "git": {
                "branch": branch,
                "is_dirty": is_dirty,
            },
            "file_count": len(repository_paths),
            "languages": dict(language_counts.most_common()),
            "extensions": dict(suffix_counts.most_common(20)),
            "top_level_directories": top_level_directories,
            "source_directory_candidates": source_candidates,
            "test_directory_candidates": test_candidates,
            "manifests": manifests,
            "lockfiles": lockfiles,
            "ci_files": ci_files,
            "documentation": documentation,
            "python": _parse_python_project(repository_root, path_set, warnings),
            "warnings": warnings,
        }
        return json.dumps(context, indent=2)

    @tool
    def list_repository_files(file_glob: str = "*") -> str:
        """List repository files matching a glob, excluding Git metadata."""

        file_glob = file_glob.strip() or "*"

        if len(file_glob) > 200 or "\n" in file_glob:
            return "File glob is invalid or too long."

        result = _run_read_only_command(
            [
                "rg",
                "--files",
                "--hidden",
                "--glob",
                "!.git/**",
                "--glob",
                file_glob,
            ],
            repository_root=repository_root,
        )

        if result is None:
            return "File listing failed because rg was unavailable or timed out."

        if result.returncode not in (0, 1):
            return f"File listing failed: {result.stderr[:1000]}"

        if not result.stdout.strip():
            return f"No files matched glob: {file_glob}"

        return _truncate_lines(
            result.stdout,
            max_lines=MAX_LISTED_FILES,
            max_chars=MAX_COMMAND_OUTPUT,
        )

    @tool
    def search_repository_files(
        query: str,
        file_glob: str = "*",
    ) -> str:
        """Search repository file contents for literal text and return paths and line numbers."""

        query = query.strip()
        file_glob = file_glob.strip() or "*"

        if not query:
            return "Search query cannot be empty."

        if len(query) > 200 or "\n" in query:
            return "Search query is invalid or too long."

        if len(file_glob) > 200 or "\n" in file_glob:
            return "File glob is invalid or too long."

        result = _run_read_only_command(
            [
                "rg",
                "--line-number",
                "--smart-case",
                "--fixed-strings",
                "--hidden",
                "--max-filesize",
                "1M",
                "--glob",
                "!.git/**",
                "--glob",
                file_glob,
                "--",
                query,
                ".",
            ],
            repository_root=repository_root,
        )

        if result is None:
            return "Repository search failed because rg was unavailable or timed out."

        if result.returncode == 1:
            return f"No matches found for: {query}"

        if result.returncode != 0:
            return f"Repository search failed: {result.stderr[:1000]}"

        return _truncate_lines(
            result.stdout,
            max_lines=MAX_SEARCH_RESULTS,
            max_chars=MAX_COMMAND_OUTPUT,
        )

    @tool
    def read_repository_file(
        relative_path: str,
        start_line: int = 1,
        end_line: int = 250,
    ) -> str:
        """Read a bounded line range from one text file inside the repository."""

        return _read_repository_file_range(
            repository_root,
            relative_path,
            start_line=start_line,
            end_line=end_line,
        )

    @tool
    def read_repository_files(
        relative_paths: list[str],
        max_lines_per_file: int = 120,
    ) -> str:
        """Read bounded excerpts from up to five related repository text files."""

        if not relative_paths:
            return "At least one file path is required."

        unique_paths = list(dict.fromkeys(relative_paths))

        if len(unique_paths) > MAX_BATCH_FILES:
            return f"A maximum of {MAX_BATCH_FILES} files can be read at once."

        if not 1 <= max_lines_per_file <= MAX_BATCH_LINES_PER_FILE:
            return (
                "max_lines_per_file must be between 1 and "
                f"{MAX_BATCH_LINES_PER_FILE}."
            )

        sections = []
        for relative_path in unique_paths:
            content = _read_repository_file_range(
                repository_root,
                relative_path,
                start_line=1,
                end_line=max_lines_per_file,
            )
            sections.append(f"=== {relative_path} ===\n{content}")

        return _truncate_lines(
            "\n\n".join(sections),
            max_lines=MAX_BATCH_FILES * (MAX_BATCH_LINES_PER_FILE + 2),
            max_chars=MAX_COMMAND_OUTPUT,
        )

    @tool
    def get_recent_git_history(
        relative_path: str | None = None,
        max_commits: int = 10,
    ) -> str:
        """Show recent commit summaries for the repository or one current repository file."""

        max_commits = max(1, min(max_commits, 25))
        command = [
            "git",
            "log",
            "--oneline",
            "--no-decorate",
            "-n",
            str(max_commits),
        ]

        if relative_path:
            try:
                file_path = _resolve_repository_file(
                    repository_root,
                    relative_path.strip(),
                )
            except ValueError as exc:
                return f"Git history access rejected: {exc}"

            if not file_path.exists():
                return f"File does not exist: {relative_path}"

            repository_relative_path = file_path.relative_to(repository_root)
            command.extend(["--", str(repository_relative_path)])

        result = _run_read_only_command(
            command,
            repository_root=repository_root,
        )

        if result is None:
            return "Git history failed because git was unavailable or timed out."

        if result.returncode != 0:
            return f"Git history failed: {result.stderr[:1000]}"

        if not result.stdout.strip():
            return "No Git history was found."

        return _truncate_lines(
            result.stdout,
            max_lines=25,
            max_chars=MAX_COMMAND_OUTPUT,
        )

    return [
        gather_repository_context,
        list_repository_files,
        search_repository_files,
        read_repository_file,
        read_repository_files,
        get_recent_git_history,
    ]
