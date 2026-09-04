from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.chief_service import ChiefApiService
from api.schemas import (
    ChiefDelegationRequest,
    ChiefDelegationResponse,
    ChiefEventsResponse,
    ChiefHandoffResponse,
    CreateHandoffRequest,
    RunResponse,
    StartRunRequest,
)
from api.service import RunConflictError, RunNotFoundError, RunService
from schemas.approval import PlanApprovalDecision
from schemas.runtime import PlannerHandoff

router = APIRouter(prefix="/api")


def get_run_service(request: Request) -> RunService:
    return request.app.state.run_service


RunServiceDependency = Annotated[RunService, Depends(get_run_service)]


def get_chief_service(request: Request) -> ChiefApiService:
    return request.app.state.chief_service


ChiefServiceDependency = Annotated[ChiefApiService, Depends(get_chief_service)]


@router.post(
    "/runs",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_run(
    request: StartRunRequest,
    service: RunServiceDependency,
) -> RunResponse:
    return await service.start_run(request)


@router.get("/runs/{thread_id}", response_model=RunResponse)
async def get_run(
    thread_id: str,
    service: RunServiceDependency,
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
    service: RunServiceDependency,
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


@router.post("/runs/{thread_id}/handoff", response_model=PlannerHandoff)
async def export_planner_handoff(
    thread_id: str,
    request: CreateHandoffRequest,
    service: RunServiceDependency,
) -> PlannerHandoff:
    try:
        return await service.create_handoff(thread_id, base_commit=request.base_commit)
    except RunNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post("/chief/handoffs", response_model=ChiefHandoffResponse)
async def accept_planner_handoff(
    handoff: PlannerHandoff,
    service: ChiefServiceDependency,
) -> ChiefHandoffResponse:
    try:
        tasks = service.accept_handoff(handoff)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return ChiefHandoffResponse(
        run_id=handoff.run_id,
        status="delegating",
        task_ids=[task.task_id for task in tasks],
        repository_path=handoff.repository_path,
    )


@router.get(
    "/chief/runs/{run_id}/integration-report",
    response_model=dict,
)
async def get_integration_report(
    run_id: str,
    service: ChiefServiceDependency,
) -> dict:
    try:
        return service.integration_report(run_id).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chief run not found: {run_id}",
        ) from exc


@router.get("/chief/runs/{run_id}", response_model=dict)
async def get_chief_status(
    run_id: str,
    service: ChiefServiceDependency,
) -> dict:
    try:
        return service.status(run_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chief run not found: {run_id}",
        ) from exc


@router.post(
    "/chief/runs/{run_id}/delegate",
    response_model=ChiefDelegationResponse,
)
async def delegate_chief_run(
    run_id: str,
    request: ChiefDelegationRequest,
    service: ChiefServiceDependency,
) -> ChiefDelegationResponse:
    try:
        assignments = service.delegate(run_id, provider=request.provider)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chief run not found: {run_id}",
        ) from exc
    return ChiefDelegationResponse(
        run_id=run_id,
        assignments=[assignment.model_dump(mode="json") for assignment in assignments],
    )


@router.get(
    "/chief/runs/{run_id}/events",
    response_model=ChiefEventsResponse,
)
async def get_chief_events(
    run_id: str,
    service: ChiefServiceDependency,
) -> ChiefEventsResponse:
    try:
        events = service.events(run_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chief run not found: {run_id}",
        ) from exc
    return ChiefEventsResponse(run_id=run_id, events=events)
