from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IssueComment(BaseModel):
    """A relevant comment from a GitHub issue."""

    model_config = ConfigDict(extra="forbid")

    author: str
    body: str


class IssueInput(BaseModel):
    """Raw GitHub issue information supplied to the workflow."""

    model_config = ConfigDict(extra="forbid")

    repository: str = Field(
        description="Repository name in owner/repository format."
    )
    number: int = Field(
        gt=0,
        description="GitHub issue number.",
    )
    title: str = Field(
        min_length=1,
        description="GitHub issue title.",
    )
    body: str = Field(
        default="",
        description="GitHub issue description.",
    )
    labels: list[str] = Field(
        default_factory=list,
        description="Labels currently applied to the issue.",
    )
    comments: list[IssueComment] = Field(
        default_factory=list,
        description="Relevant comments from the issue discussion.",
    )
    url: str | None = Field(
        default=None,
        description="URL of the original GitHub issue.",
    )


class IssueRisk(BaseModel):
    """A risk discovered while analyzing the issue."""

    model_config = ConfigDict(extra="forbid")

    folder: str | None = Field(
        default=None,
        description="Repository folder associated with the risk, if known.",
    )
    description: str
    severity: Literal["low", "medium", "high"]


class IssueBrief(BaseModel):
    """Structured analysis produced by the issue analyst."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(
        description="A concise summary of the requested change."
    )
    problem_statement: str = Field(
        description="The underlying problem that needs to be solved."
    )
    requirements: list[str] = Field(
        description="Specific functional requirements extracted from the issue."
    )
    acceptance_criteria: list[str] = Field(
        description="Observable conditions that indicate the issue is complete."
    )
    in_scope: list[str] = Field(
        description="Work that should be included in the implementation."
    )
    out_of_scope: list[str] = Field(
        description="Related work that should not be included."
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Assumptions made because the issue lacks information.",
    )
    open_questions: list[str] = Field(
        default_factory=list,
        description="Questions that may require human clarification.",
    )
    risks: list[IssueRisk] = Field(
        default_factory=list,
        description="Potential implementation or compatibility risks.",
    )
    is_actionable: bool = Field(
        description="Whether the issue has enough information to continue."
    )
    actionability_reason: str = Field(
        description="Explanation of why the issue is or is not actionable."
    )
