import json
from functools import lru_cache
from pathlib import Path
from typing import Any

PROMPTS_ROOT = (Path(__file__).resolve().parent.parent / "prompts").resolve()


def _resolve_prompt_path(relative_path: str) -> Path:
    """Resolve a prompt path while preventing access outside the prompt folder."""

    requested_path = Path(relative_path)

    if requested_path.is_absolute():
        raise ValueError("Prompt paths must be relative to the prompts directory.")

    resolved_path = (PROMPTS_ROOT / requested_path).resolve()

    try:
        resolved_path.relative_to(PROMPTS_ROOT)
    except ValueError as exc:
        raise ValueError("Prompt path escapes the prompts directory.") from exc

    return resolved_path


@lru_cache(maxsize=32)
def load_prompt(relative_path: str) -> str:
    """Load and cache a text prompt from ``src/prompts``."""

    prompt_path = _resolve_prompt_path(relative_path)

    if not prompt_path.is_file():
        raise FileNotFoundError(f"Prompt file does not exist: {relative_path}")

    prompt = prompt_path.read_text(encoding="utf-8").strip()

    if not prompt:
        raise ValueError(f"Prompt file is empty: {relative_path}")

    return prompt


def load_prompt_examples(relative_path: str) -> list[dict[str, Any]]:
    """Load and validate few-shot examples stored as a JSON list."""

    raw_examples = json.loads(load_prompt(relative_path))

    if not isinstance(raw_examples, list):
        raise TypeError("Few-shot prompt examples must be a JSON list.")

    examples: list[dict[str, Any]] = []

    for index, example in enumerate(raw_examples):
        if not isinstance(example, dict):
            raise TypeError(f"Prompt example {index} must be a JSON object.")

        if not isinstance(example.get("input"), str):
            raise TypeError(f"Prompt example {index} must contain string input.")

        if not isinstance(example.get("output"), dict):
            raise TypeError(f"Prompt example {index} must contain object output.")

        examples.append(example)

    return examples
