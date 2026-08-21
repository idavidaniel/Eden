"""FastAPI application for the AI-company platform."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import chat, companies, employees, projects, wiki, workspace
from config import get_settings
from db import init_db
from mcp_registry.auth import MockOAuthMiddleware
from mcp_registry.server import router as mcp_router

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
    yield


def _release_orphaned_runs() -> None:
    """A run lives in a worker thread; a restart kills it mid-flight.

    Without this, those runs stay 'running' forever and block new ones.
    """
    from sqlalchemy import select

    from db import session
    from models import Employee, Run

    db = session()
    try:
        stale = list(db.scalars(select(Run).where(Run.status.in_(["queued", "running", "paused"]))))
        for run in stale:
            run.status = "interrupted"
            run.error = "The server restarted while this run was in flight."
            db.add(run)
        for employee in db.scalars(select(Employee).where(Employee.status == "working")):
            employee.status, employee.status_note = "idle", None
            db.add(employee)
        if stale:
            log.warning("Released %s interrupted run(s)", len(stale))
        db.commit()
    finally:
        db.close()


app = FastAPI(
    title="Eden — AI Employees as a Service",
    version="0.2.0",
    summary="Create companies, hire AI employees, and let them deliver projects together.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(MockOAuthMiddleware)

for router in (
    companies.router,
    employees.router,
    projects.router,
    wiki.router,
    chat.router,
    workspace.router,
):
    app.include_router(router)
app.include_router(mcp_router)


@app.get("/health", tags=["ops"])
def health():
    settings = get_settings()
    return {
        "status": "ok",
        "model": settings.model,
        "llm_configured": bool(settings.nvidia_api_key),
        "persistence": "postgres" if settings.database_url else "unconfigured",
        "workspaces": settings.workspaces_dir,
    }
