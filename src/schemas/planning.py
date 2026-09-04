from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ImplementationStep(BaseModel):
    """One ordered step in an implementation plan."""

    model_config = ConfigDict(extra="forbid")

    order: int = Field(
        ge=1,
        description="One-based execution order for this step.",
    )
    description: str = Field(
        description="The concrete change to make without including code."
    )
    affected_files: list[str] = Field(
        default_factory=list,
        description="Repository-relative files expected to change.",
    )
    rationale: str = Field(
        description="Why this step is needed to satisfy the issue."
    )
    depends_on: list[int] = Field(
        default_factory=list,
        description="Earlier step order values that must finish first.",
    )

    @model_validator(mode="after")
    def dependencies_must_be_earlier_steps(self):
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("Step dependencies must be unique.")
        if any(dependency >= self.order or dependency < 1 for dependency in self.depends_on):
            raise ValueError("Step dependencies must point to earlier steps.")
        return self


class PlannedTest(BaseModel):
    """A test that should verify the planned implementation."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(
        description="Behavior or acceptance criterion the test will verify."
    )
    test_type: Literal["unit", "integration", "end_to_end"] = Field(
        description="The scope of the planned test."
    )
    target_file: str | None = Field(
        default=None,
        description="Repository-relative test file, when known from evidence.",
    )


class ImplementationPlan(BaseModel):
    """A reviewable, implementation-ready plan produced before code editing."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(
        description="Concise summary of the proposed implementation."
    )
    approach: str = Field(
        description="Overall technical approach grounded in repository evidence."
    )
    steps: list[ImplementationStep] = Field(
        min_length=1,
        description="Ordered implementation steps.",
    )
    planned_tests: list[PlannedTest] = Field(
        default_factory=list,
        description="Tests required to verify the acceptance criteria.",
    )
    risks: list[str] = Field(
        default_factory=list,
        description="Implementation or compatibility risks to review.",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Assumptions not directly established by repository evidence.",
    )
    blocking_questions: list[str] = Field(
        default_factory=list,
        description="Questions that must be answered before code editing begins.",
    )
    ready_for_approval: bool = Field(
        description="Whether the plan is complete enough for human approval."
    )

    @model_validator(mode="after")
    def ready_plans_cannot_have_blocking_questions(self):
        if self.ready_for_approval and self.blocking_questions:
            raise ValueError(
                "A plan with blocking questions cannot be ready for approval."
            )
        return self
