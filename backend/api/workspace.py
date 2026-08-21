"""The code workspace: file tree, file contents, git history and diffs."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from services import events, workspace
from services.workspace import WorkspaceError

from .projects import get_project

router = APIRouter(tags=["workspace"])


class FileIn(BaseModel):
    path: str
    content: str
    commit_message: str | None = None


def _space(db: Session, project_id: str):
    project = get_project(db, project_id)
    space = workspace.for_project(project.company.slug, project.key)
    space.init(project.name)
    return project, space


@router.get("/projects/{project_id}/files")
def list_files(project_id: str, db: Session = Depends(get_db)):
    project, space = _space(db, project_id)
    return {"project_id": project.id, "root": str(space.root), "entries": space.tree()}


@router.get("/projects/{project_id}/file")
def read_file(project_id: str, path: str = Query(...), db: Session = Depends(get_db)):
    _, space = _space(db, project_id)
    try:
        return {"path": path, "content": space.read(path)}
    except WorkspaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/projects/{project_id}/file")
def write_file(project_id: str, payload: FileIn, db: Session = Depends(get_db)):
    project, space = _space(db, project_id)
    try:
        result = space.write(payload.path, payload.content)
        commit = None
        if payload.commit_message:
            commit = space.commit(payload.commit_message, ("You", "you@eden.local"))
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    events.record(
        db,
        company_id=project.company_id,
        project_id=project.id,
        actor="You",
        kind="code.write",
        summary=f"{'created' if result['created'] else 'edited'} {payload.path}",
        payload={"path": payload.path},
    )
    db.commit()
    return {**result, "commit": commit}


@router.get("/projects/{project_id}/commits")
def list_commits(project_id: str, limit: int = 40, db: Session = Depends(get_db)):
    _, space = _space(db, project_id)
    return space.log(limit)


@router.get("/projects/{project_id}/commits/{sha}")
def read_commit(project_id: str, sha: str, db: Session = Depends(get_db)):
    _, space = _space(db, project_id)
    try:
        return {"sha": sha, "diff": space.diff(sha)}
    except WorkspaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
