from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.approval import PlanApprovalDecision
from schemas.issue import IssueBrief
from schemas.planning import ImplementationPlan
from schemas.repository import RepositoryMap


class WorkerAssignment(BaseModel):
    """The guarded Runtime scope assigned to one worker."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    worker_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    project_workspace: str = Field(min_length=1)
    worktree_path: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    base_commit: str = Field(min_length=1)
    assigned_paths: list[str] = Field(min_length=1)
    approved_checks: list[list[str]] = Field(default_factory=list)
    required_skills: list[str] = Field(
        default_factory=lambda: ["implement", "tdd", "code-review"]
    )
    protected_branches: list[str] = Field(
        default_factory=lambda: ["main", "master"]
    )
    provider: Literal["codex", "claude"] = "codex"
    timeout_seconds: int = Field(default=3_600, ge=1, le=86_400)


class WorkerTask(BaseModel):
    """A vertical-slice ticket that Chief assigns to one Runtime worker."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    blocked_by: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(min_length=1)
    assigned_paths: list[str] = Field(min_length=1)
    required_checks: list[list[str]] = Field(default_factory=list)
    required_skills: list[str] = Field(
        default_factory=lambda: ["implement", "tdd", "code-review"]
    )


class QueueEntry(BaseModel):
    """One append-only task or change request in a worker queue."""

    model_config = ConfigDict(extra="forbid")

    queue_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    worker_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    priority: Literal["immediate", "error_detection", "workflow"]
    kind: Literal["task", "change_request"]
    task_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    blocked_by: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    assigned_paths: list[str] = Field(default_factory=list)
    required_checks: list[list[str]] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    supersedes_entry_id: str | None = None

    @model_validator(mode="after")
    def change_requests_must_point_to_an_entry(self):
        if self.kind == "change_request" and not self.supersedes_entry_id:
            raise ValueError(
                "A change request must point to the queue entry it changes."
            )
        return self


class SkillTrace(BaseModel):
    """Evidence that a Runtime worker followed one part of its skill route."""

    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    skill: str = Field(min_length=1)
    phase: Literal["started", "red", "green", "reviewed", "completed", "failed"]
    status: Literal["started", "completed", "failed"]
    evidence: dict[str, object] = Field(default_factory=dict)


class CheckObservation(BaseModel):
    """A named check reported by a Runtime worker."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    status: Literal["passed", "failed", "timed_out"]


class WorkerResult(BaseModel):
    """The evidence package a Runtime worker gives back to Chief."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    worker_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    status: Literal["completed", "failed", "blocked"]
    commit: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    checks: list[CheckObservation] = Field(default_factory=list)
    skill_trace: list[SkillTrace] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class PlannerHandoff(BaseModel):
    """Versioned, approved planning artifacts handed to Chief."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    repository_path: str = Field(min_length=1)
    base_commit: str = Field(min_length=1)
    issue_brief: IssueBrief
    repository_map: RepositoryMap
    implementation_plan: ImplementationPlan
    plan_approval: PlanApprovalDecision
    approved_checks: list[list[str]] = Field(default_factory=list)
    created_at: str = Field(min_length=1)

    @field_validator("repository_path")
    @classmethod
    def repository_path_must_be_absolute(cls, value: str) -> str:
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError("repository_path must be absolute.")
        return str(path.resolve())

    @model_validator(mode="after")
    def handoff_must_be_approved(self):
        if self.plan_approval.action != "approve":
            raise ValueError("Only approved plans can cross the Chief boundary.")
        if not self.implementation_plan.ready_for_approval:
            raise ValueError("Only ready plans can cross the Chief boundary.")
        return self


class IntegrationReport(BaseModel):
    """Human-facing summary of accepted worker branches."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    status: Literal["ready_for_human", "blocked"]
    accepted_workers: list[str] = Field(default_factory=list)
    worker_commits: dict[str, str] = Field(default_factory=dict)
    changed_files: dict[str, list[str]] = Field(default_factory=dict)
    overlapping_files: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    next_action: str = Field(min_length=1)


class PatchResult(BaseModel):
    """The result of one accepted Runtime patch."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["applied"]
    changed_files: list[str]


class CheckResult(BaseModel):
    """The bounded result of one approved Runtime check."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["passed", "failed", "timed_out"]
    argv: list[str]
    exit_code: int | None
    stdout: str
    stderr: str


class GitResult(BaseModel):
    """A bounded result from a Runtime worker Git action."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["clean", "changes", "committed", "no_changes"]
    branch: str
    output: str = ""
    commit: str | None = None
