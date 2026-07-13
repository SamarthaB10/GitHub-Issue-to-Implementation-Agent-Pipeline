from typing_extensions import NotRequired, TypedDict

from schemas.approval import PlanApprovalDecision
from schemas.issue import IssueBrief, IssueInput
from schemas.planning import ImplementationPlan
from schemas.repository import RepositoryMap


class AgentState(TypedDict):
    """Shared information retained throughout one workflow run."""

    issue: IssueInput
    repository_path: str
    issue_brief: NotRequired[IssueBrief]
    repository_map: NotRequired[RepositoryMap]
    implementation_plan: NotRequired[ImplementationPlan]
    plan_approval: NotRequired[PlanApprovalDecision]
    plan_feedback: NotRequired[str]
    status: NotRequired[str]
    error: NotRequired[str]
