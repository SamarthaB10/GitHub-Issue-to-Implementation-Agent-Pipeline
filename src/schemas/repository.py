from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RelevantFile(BaseModel):
    """A repository file supported by evidence from the exploration."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        description="Path relative to the repository root."
    )
    reason: str = Field(
        description="Why this file is relevant to the approved issue brief."
    )
    important_symbols: list[str] = Field(
        default_factory=list,
        description="Relevant functions, classes, constants, or configuration keys.",
    )


class RepositoryRisk(BaseModel):
    """A repository-specific risk discovered through tool evidence."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(
        description="The risk and the repository evidence supporting it."
    )
    severity: Literal["low", "medium", "high"] = Field(
        description="Estimated severity if the risk is not addressed."
    )


class RepositoryMap(BaseModel):
    """Structured repository findings produced by the explorer."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(
        description="Concise explanation of how the repository relates to the issue."
    )
    relevant_files: list[RelevantFile] = Field(
        description="Existing files that are directly relevant to the change."
    )
    coding_conventions: list[str] = Field(
        default_factory=list,
        description="Observed conventions the implementation should follow.",
    )
    related_tests: list[str] = Field(
        default_factory=list,
        description="Existing test files or test cases related to the change.",
    )
    suggested_tests: list[str] = Field(
        default_factory=list,
        description="Tests that should be added or updated for this issue.",
    )
    risks: list[RepositoryRisk] = Field(
        default_factory=list,
        description="Repository-specific implementation or compatibility risks.",
    )
    open_questions: list[str] = Field(
        default_factory=list,
        description="Questions that repository evidence could not answer.",
    )
