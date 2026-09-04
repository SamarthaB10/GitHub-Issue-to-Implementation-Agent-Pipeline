import ast
import json
from pathlib import Path

from langchain.tools import tool

from agents.tools.repository_tools import (
    MAX_COMMAND_OUTPUT,
    MAX_FILE_SIZE_BYTES,
    _resolve_repository_file,
)

MAX_AST_ITEMS = 200


def _decorator_names(node) -> list[str]:
    return [ast.unparse(decorator) for decorator in node.decorator_list]


def _argument_names(arguments: ast.arguments) -> list[str]:
    names = [
        argument.arg
        for argument in [*arguments.posonlyargs, *arguments.args]
    ]
    if arguments.vararg:
        names.append(f"*{arguments.vararg.arg}")
    names.extend(argument.arg for argument in arguments.kwonlyargs)
    if arguments.kwarg:
        names.append(f"**{arguments.kwarg.arg}")
    return names


def _function_summary(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    return {
        "name": node.name,
        "line": node.lineno,
        "end_line": node.end_lineno,
        "is_async": isinstance(node, ast.AsyncFunctionDef),
        "arguments": _argument_names(node.args),
        "decorators": _decorator_names(node),
    }


def build_python_tools(repository_path: str):
    """Create Python-specific read-only tools for one repository root."""

    repository_root = Path(repository_path).expanduser().resolve()

    if not repository_root.is_dir():
        raise ValueError(f"Repository does not exist: {repository_root}")

    @tool
    def inspect_python_file(relative_path: str) -> str:
        """Parse a Python file without executing it and return its imports, classes, functions, and line numbers."""

        try:
            file_path = _resolve_repository_file(repository_root, relative_path)
        except ValueError as exc:
            return f"Python file inspection rejected: {exc}"

        if file_path.suffix != ".py":
            return "inspect_python_file only accepts .py files."

        if not file_path.is_file():
            return f"File does not exist: {relative_path}"

        if file_path.stat().st_size > MAX_FILE_SIZE_BYTES:
            return "Python file is too large to inspect."

        source = file_path.read_text(encoding="utf-8", errors="replace")

        try:
            tree = ast.parse(source, filename=relative_path)
        except SyntaxError as exc:
            return json.dumps(
                {
                    "path": relative_path,
                    "syntax_error": {
                        "message": exc.msg,
                        "line": exc.lineno,
                        "offset": exc.offset,
                    },
                },
                indent=2,
            )

        imports = []
        classes = []
        functions = []

        for node in tree.body:
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports.extend(
                    f"{module}.{alias.name}".strip(".") for alias in node.names
                )
            elif isinstance(node, ast.ClassDef):
                methods = [
                    _function_summary(child)
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                classes.append(
                    {
                        "name": node.name,
                        "line": node.lineno,
                        "end_line": node.end_lineno,
                        "bases": [ast.unparse(base) for base in node.bases],
                        "decorators": _decorator_names(node),
                        "methods": methods,
                    }
                )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(_function_summary(node))

        truncated = len(classes) + len(functions) > MAX_AST_ITEMS
        result = {
            "path": relative_path,
            "module_docstring": (ast.get_docstring(tree) or "")[:1_000] or None,
            "imports": list(dict.fromkeys(imports))[:MAX_AST_ITEMS],
            "classes": classes[:MAX_AST_ITEMS],
            "functions": functions[:MAX_AST_ITEMS],
            "truncated": truncated,
        }
        serialized = json.dumps(result, indent=2)

        if len(serialized) > MAX_COMMAND_OUTPUT:
            return serialized[:MAX_COMMAND_OUTPUT] + "\n... output truncated ..."

        return serialized

    return [inspect_python_file]
