import asyncio
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from langgraph.types import Command

from agents.handoff import build_planner_handoff
from api.schemas import RunResponse, StartRunRequest
from schemas.approval import PlanApprovalDecision


class RunNotFoundError(LookupError):
    """Raised when an API request references an unknown workflow run."""


class RunConflictError(RuntimeError):
    """Raised when an operation is invalid for the run's current state."""


class RunService:
    """Start, inspect, and resume workflow runs through one compiled graph."""

    def __init__(self, graph):
        self.graph = graph
        self._known_threads: set[str] = set()
        self._locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def _config(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    async def start_run(self, request: StartRunRequest) -> RunResponse:
        thread_id = uuid4().hex
        self._known_threads.add(thread_id)
        self._locks[thread_id] = asyncio.Lock()

        try:
            await self.graph.ainvoke(
                {
                    "issue": request.issue,
                    "repository_path": request.repository_path,
                },
                config=self._config(thread_id),
            )
        except Exception:
            self._known_threads.discard(thread_id)
            self._locks.pop(thread_id, None)
            raise

        return await self.get_run(thread_id)

    async def get_run(self, thread_id: str) -> RunResponse:
        self._require_known_thread(thread_id)
        snapshot = await self.graph.aget_state(self._config(thread_id))
        return self._snapshot_to_response(thread_id, snapshot)

    async def submit_plan_decision(
        self,
        thread_id: str,
        decision: PlanApprovalDecision,
    ) -> RunResponse:
        self._require_known_thread(thread_id)

        async with self._locks[thread_id]:
            snapshot = await self.graph.aget_state(self._config(thread_id))

            if "plan_approval" not in snapshot.next:
                raise RunConflictError(
                    "Run is not waiting for a plan approval decision."
                )

            await self.graph.ainvoke(
                Command(
                    resume=decision.model_dump(exclude_none=True),
                ),
                config=self._config(thread_id),
            )

            return await self.get_run(thread_id)

    async def create_handoff(self, thread_id: str, *, base_commit: str):
        self._require_known_thread(thread_id)
        snapshot = await self.graph.aget_state(self._config(thread_id))
        state = dict(snapshot.values)
        state["thread_id"] = thread_id
        return build_planner_handoff(state, base_commit=base_commit)

    def _require_known_thread(self, thread_id: str) -> None:
        if thread_id not in self._known_threads:
            raise RunNotFoundError(f"Workflow run not found: {thread_id}")

    @staticmethod
    def _snapshot_to_response(thread_id: str, snapshot) -> RunResponse:
        interrupt_payload = None

        if snapshot.interrupts:
            interrupt_payload = jsonable_encoder(snapshot.interrupts[0].value)

        state = jsonable_encoder(dict(snapshot.values))
        pending_nodes = list(snapshot.next)

        return RunResponse(
            thread_id=thread_id,
            status=state.get("status"),
            state=state,
            pending_nodes=pending_nodes,
            interrupt=interrupt_payload,
            completed=not pending_nodes,
        )
