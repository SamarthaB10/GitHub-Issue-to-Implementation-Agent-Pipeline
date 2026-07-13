from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.schemas import RunResponse, StartRunRequest
from api.service import RunConflictError, RunNotFoundError, RunService
from schemas.approval import PlanApprovalDecision


router = APIRouter(prefix="/api")


def get_run_service(request: Request) -> RunService:
    return request.app.state.run_service


@router.post(
    "/runs",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_run(
    request: StartRunRequest,
    service: RunService = Depends(get_run_service),
) -> RunResponse:
    return await service.start_run(request)


@router.get("/runs/{thread_id}", response_model=RunResponse)
async def get_run(
    thread_id: str,
    service: RunService = Depends(get_run_service),
) -> RunResponse:
    try:
        return await service.get_run(thread_id)
    except RunNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/runs/{thread_id}/decision",
    response_model=RunResponse,
)
async def submit_plan_decision(
    thread_id: str,
    decision: PlanApprovalDecision,
    service: RunService = Depends(get_run_service),
) -> RunResponse:
    try:
        return await service.submit_plan_decision(thread_id, decision)
    except RunNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except RunConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
