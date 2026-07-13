from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PlanApprovalDecision(BaseModel):
    """A human decision about a proposed implementation plan."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "request_changes", "cancel"] = Field(
        description="How the workflow should proceed after plan review."
    )
    feedback: str | None = Field(
        default=None,
        description="Human feedback, required when requesting plan changes.",
    )

    @model_validator(mode="after")
    def requested_changes_require_feedback(self):
        if self.action == "request_changes" and not (
            self.feedback and self.feedback.strip()
        ):
            raise ValueError(
                "feedback is required when action is request_changes."
            )
        return self
