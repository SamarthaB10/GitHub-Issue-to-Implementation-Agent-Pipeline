from fastapi import FastAPI

from agents.graph.workflow import build_workflow
from api.chief_service import ChiefApiService
from api.routes import router
from api.service import RunService


def create_app(
    run_service: RunService | None = None,
    chief_service: ChiefApiService | None = None,
) -> FastAPI:
    """Create the API with an injectable run service for offline tests."""

    app = FastAPI(
        title="GitHub Issue-to-PR Agent Team",
        version="0.1.0",
    )
    app.state.run_service = run_service or RunService(build_workflow())
    app.state.chief_service = chief_service or ChiefApiService()
    app.include_router(router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
