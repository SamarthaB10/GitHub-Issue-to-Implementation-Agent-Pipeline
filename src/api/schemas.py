from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemas.issue import IssueInput


class StartRunRequest(BaseModel):
    """Input required to start one local workflow run."""

    model_config = ConfigDict(extra="forbid")

    issue: IssueInput
    repository_path: str = Field(
        description="Absolute path to the trusted local repository."
    )

    @field_validator("repository_path")
    @classmethod
    def repository_must_be_an_absolute_directory(cls, value: str) -> str:
        path = Path(value).expanduser()

        if not path.is_absolute():
            raise ValueError("repository_path must be absolute.")

        resolved_path = path.resolve()

        if not resolved_path.is_dir():
            raise ValueError("repository_path must be an existing directory.")

        return str(resolved_path)


class RunResponse(BaseModel):
    """Serializable workflow state and pause/completion information."""

    model_config = ConfigDict(extra="forbid")

    thread_id: str
    status: str | None
    state: dict[str, Any]
    pending_nodes: list[str]
    interrupt: dict[str, Any] | None = None
    completed: bool
