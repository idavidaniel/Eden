"""FastAPI application for the AI-company platform."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api import agents, chat, companies, connections, employees, ops, preview, projects, wiki
from api import workspace as workspace_api
from config import get_settings
from db import init_db
from mcp_registry.auth import AgentTokenMiddleware
from mcp_registry.server import router as mcp_router
from services import clock
from services import preview as preview_service

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if get_settings().database_url:
        try:
            init_db()
            _release_orphaned_runs()
        except Exception:
            log.exception(
                "Schema setup failed - the API will error until the database is reachable"
            )
        if clock.enabled():
            clock.start()
    yield
    clock.stop()


def _release_orphaned_runs() -> None:
    """A run lives in a worker thread; a restart kills it mid-flight.

    Without this, those runs stay 'running' forever and block new ones. Leased
    agent tasks are reclaimed the same way — by the clock, on its first tick.
    """
    from sqlalchemy import select

    from db import session
    from models import AgentTask, Employee, Run

    db = session()
    try:
        stale = list(db.scalars(select(Run).where(Run.status.in_(["queued", "running", "paused"]))))
        for run in stale:
            run.status = "interrupted"
            run.error = "The server restarted while this run was in flight."
            db.add(run)
        for task in db.scalars(
            select(AgentTask).where(AgentTask.status.in_(["leased", "running"]))
        ):
            task.status = "queued"
            task.lease_until = None
            db.add(task)
        for employee in db.scalars(select(Employee).where(Employee.status == "working")):
            employee.status, employee.status_note, employee.heartbeat_at = "idle", None, None
            db.add(employee)
        if stale:
            log.warning("Released %s interrupted run(s)", len(stale))
        db.commit()
    finally:
        db.close()


app = FastAPI(
    title="Eden — AI employees you can address, and work you can prove",
    version="2.0.0",
    summary=(
        "Companies in any industry, staffed by agents with their own memory, "
        "credentials and API, producing deliverables the platform verifies itself."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AgentTokenMiddleware)

for router in (
    companies.router,
    employees.router,
    agents.router,
    projects.router,
    ops.router,
    connections.router,
    preview.router,
    wiki.router,
    chat.router,
    workspace_api.router,
):
    app.include_router(router)
app.include_router(mcp_router)

# Built web previews are served straight from disk, so a finished app can be
# opened in the browser from the dashboard.
_previews = preview_service.previews_root()
_previews.mkdir(parents=True, exist_ok=True)
app.mount("/preview", StaticFiles(directory=str(_previews), html=True), name="preview")


@app.get("/health", tags=["ops"])
def health():
    from services import embeddings, runners

    settings = get_settings()
    return {
        "status": "ok",
        "model": settings.model,
        "llm_configured": bool(settings.nvidia_api_key),
        "persistence": "postgres" if settings.database_url else "unconfigured",
        "workspaces": settings.workspaces_dir,
        "embeddings": embeddings.status(),
        "clock": clock.status(),
        "runners": runners.status(),
    }
