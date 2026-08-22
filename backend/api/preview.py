"""Building and serving a web preview of a project's Flutter app."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agents import engine
from db import get_db, session
from models import Project
from services import events, preview, workspace

from .projects import get_project

router = APIRouter(tags=["preview"])


class PreviewIn(BaseModel):
    # Directory holding the pubspec.yaml, relative to the workspace root.
    package: str


def _run_build(project_id: str) -> None:
    """Background worker: build, then write the result back to the project."""
    db = session()
    try:
        project = db.get(Project, project_id)
        if not project:
            return
        company = project.company
        package = (project.preview or {}).get("package", ".")

        state = preview.build(company.slug, project.key, project.name, package)
        project.preview = state
        db.add(project)
        events.record(
            db,
            company_id=company.id,
            project_id=project.id,
            actor="Preview",
            kind="preview.built" if state["status"] == "ready" else "preview.failed",
            summary=(
                f"web preview of {package} is ready"
                if state["status"] == "ready"
                else f"web preview of {package} failed to build"
            ),
            payload={"package": package, "status": state["status"]},
        )
        db.commit()

        # A failed preview is a compile error with a full log attached: hand it
        # straight to an engineer instead of waiting to be asked.
        if state["status"] == "failed" and (project.preview or {}).get("autofix", True):
            href = preview.base_href(company.slug, project.key, package)
            engine.get_executor().submit(
                engine.debug_until_green,
                project.id,
                f"flutter build web --release --base-href={href}",
                "" if package == "." else package,
                None,
                "preview build",
            )
    except Exception as exc:  # never leave the UI spinning
        db.rollback()
        project = db.get(Project, project_id)
        if project:
            project.preview = {"status": "failed", "error": str(exc)[:2000]}
            db.add(project)
            db.commit()
    finally:
        db.close()


@router.get("/projects/{project_id}/packages")
def list_packages(project_id: str, db: Session = Depends(get_db)):
    """Flutter packages in the workspace, i.e. anything with a pubspec.yaml."""
    project = get_project(db, project_id)
    space = workspace.for_project(project.company.slug, project.key)
    space.init(project.name)
    return {"packages": preview.flutter_packages(space)}


@router.get("/projects/{project_id}/preview")
def read_preview(project_id: str, db: Session = Depends(get_db)):
    return get_project(db, project_id).preview or {"status": "none"}


@router.post("/projects/{project_id}/preview", status_code=202)
def build_preview(project_id: str, payload: PreviewIn, db: Session = Depends(get_db)):
    project = get_project(db, project_id)
    if (project.preview or {}).get("status") == "building":
        raise HTTPException(status_code=409, detail="A preview build is already running.")

    space = workspace.for_project(project.company.slug, project.key)
    space.init(project.name)
    if payload.package not in preview.flutter_packages(space):
        raise HTTPException(status_code=400, detail=f"No pubspec.yaml in '{payload.package}'.")

    project.preview = {"status": "building", "package": payload.package, "error": None}
    db.add(project)
    events.record(
        db,
        company_id=project.company_id,
        project_id=project.id,
        actor="You",
        kind="preview.building",
        summary=f"building a web preview of {payload.package}",
    )
    db.commit()

    preview.submit(_run_build, project.id)
    return project.preview
