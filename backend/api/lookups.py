"""Fetching one row by id, and refusing it if it is not the caller's.

`get_company` covers routes shaped like `/companies/{id}/…`. Plenty are not:
`/projects/{id}`, `/work-items/{id}`, `/artifacts/{id}`, `/employees/{id}`.
Those take an id that identifies a company indirectly, and a lookup that only
does `db.get(Model, id)` will happily hand over another tenant's row to anyone
who knows a UUID.

So every one of them goes through here. Each function walks the row back to the
company that owns it and checks the tenant, and each answers 404 for both
"missing" and "not yours" — because distinguishing them would turn these
endpoints into a way to confirm that somebody else's records exist.
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import (
    AgentTask,
    Approval,
    Artifact,
    AuthoredTool,
    Channel,
    Company,
    Connection,
    Document,
    Employee,
    McpServer,
    Meeting,
    Project,
    Run,
    WorkItem,
)

from .scope import require_caller

_MISSING = "Not found."


def _refuse(what: str = "") -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} not found." if what else _MISSING)


def _tenant() -> str:
    return require_caller().tenant_id


def _owns(db: Session, company_id: str | None) -> bool:
    if not company_id:
        return False
    company = db.get(Company, company_id)
    return bool(company and company.tenant_id == _tenant())


# --------------------------------------------------------------------------


def employee(db: Session, employee_id: str) -> Employee:
    row = db.get(Employee, employee_id)
    if not row or not _owns(db, row.company_id):
        raise _refuse("Employee")
    return row


def project(db: Session, project_id: str) -> Project:
    row = db.get(Project, project_id)
    if not row or not _owns(db, row.company_id):
        raise _refuse("Project")
    return row


def work_item(db: Session, work_item_id: str) -> WorkItem:
    row = db.get(WorkItem, work_item_id)
    if not row:
        raise _refuse("Work item")
    parent = db.get(Project, row.project_id)
    if not parent or not _owns(db, parent.company_id):
        raise _refuse("Work item")
    return row


def artifact(db: Session, artifact_id: str) -> Artifact:
    row = db.get(Artifact, artifact_id)
    if not row or not _owns(db, row.company_id):
        raise _refuse("Artifact")
    return row


def run(db: Session, run_id: str) -> Run:
    row = db.get(Run, run_id)
    if not row or not _owns(db, row.company_id):
        raise _refuse("Run")
    return row


def document(db: Session, document_id: str) -> Document:
    row = db.get(Document, document_id)
    if not row or not _owns(db, row.company_id):
        raise _refuse("Document")
    return row


def channel(db: Session, channel_id: str) -> Channel:
    row = db.get(Channel, channel_id)
    if not row or not _owns(db, row.company_id):
        raise _refuse("Channel")
    return row


def meeting(db: Session, meeting_id: str) -> Meeting:
    row = db.get(Meeting, meeting_id)
    if not row or not _owns(db, row.company_id):
        raise _refuse("Meeting")
    return row


def approval(db: Session, approval_id: str) -> Approval:
    row = db.get(Approval, approval_id)
    if not row or not _owns(db, row.company_id):
        raise _refuse("Approval")
    return row


def agent_task(db: Session, task_id: str) -> AgentTask:
    row = db.get(AgentTask, task_id)
    if not row or not _owns(db, row.company_id):
        raise _refuse("Task")
    return row


def authored_tool(db: Session, tool_id: str) -> AuthoredTool:
    row = db.get(AuthoredTool, tool_id)
    if not row or not _owns(db, row.company_id):
        raise _refuse("Tool")
    return row


def connection(db: Session, connection_id: str) -> Connection:
    row = db.get(Connection, connection_id)
    if not row or not _owns(db, row.company_id):
        raise _refuse("Connection")
    return row


def mcp_server(db: Session, server_id: str) -> McpServer:
    row = db.get(McpServer, server_id)
    if not row or not _owns(db, row.company_id):
        raise _refuse("Server")
    return row
