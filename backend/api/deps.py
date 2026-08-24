"""Shared FastAPI dependencies: who is calling, and may they.

Two kinds of caller. You, through the dashboard — trusted, because this runs on
your machine behind whatever you put in front of it. And an agent token, which
authenticates as one specific employee and carries scopes. The second one is
what turns the credentials on an employee's profile from set dressing into the
actual key to that employee.
"""

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from db import get_db
from models import AgentToken, Company, Employee
from services import tokens


@dataclass
class AgentPrincipal:
    token: AgentToken
    employee: Employee
    company: Company

    def require(self, scope: str) -> None:
        if not tokens.has_scope(self.token, scope):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"This token does not carry the '{scope}' scope. "
                    f"It has: {', '.join(self.token.scopes or []) or 'nothing'}."
                ),
            )


def _bearer(request: Request, authorization: str | None) -> str | None:
    header = authorization or request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def optional_agent(
    request: Request,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AgentPrincipal | None:
    presented = _bearer(request, authorization)
    if not presented:
        return None
    row = tokens.verify(db, presented)
    if not row:
        return None
    employee = db.get(Employee, row.employee_id)
    if not employee or not employee.api_enabled:
        return None
    return AgentPrincipal(token=row, employee=employee, company=employee.company)


def current_agent(
    request: Request,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AgentPrincipal:
    presented = _bearer(request, authorization)
    if not presented:
        raise HTTPException(
            status_code=401,
            detail="Send an agent token: Authorization: Bearer edn_<prefix>_<secret>",
            headers={"WWW-Authenticate": 'Bearer realm="eden"'},
        )
    row = tokens.verify(db, presented)
    if not row:
        raise HTTPException(
            status_code=401,
            detail="That token is not valid, has expired, or has been revoked.",
            headers={"WWW-Authenticate": 'Bearer realm="eden"'},
        )
    employee = db.get(Employee, row.employee_id)
    if not employee:
        raise HTTPException(status_code=401, detail="That token's employee no longer exists.")
    if not employee.api_enabled:
        raise HTTPException(
            status_code=403, detail=f"{employee.name}'s API access is switched off."
        )
    company = employee.company
    if company.halted:
        raise HTTPException(
            status_code=409,
            detail=f"{company.name} is halted: {company.halt_reason or 'stopped by the operator'}",
        )
    return AgentPrincipal(token=row, employee=employee, company=company)


def get_employee(db: Session, employee_id: str) -> Employee:
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found.")
    return employee


def authorise_for(
    employee_id: str, scope: str, principal: AgentPrincipal | None, db: Session
) -> Employee:
    """Either you are asking, or the token belongs to this employee.

    A token is the key to *one* agent. It cannot be used to drive a colleague,
    which is what stops one compromised agent from becoming all of them.
    """
    employee = get_employee(db, employee_id)
    if principal is None:
        return employee
    if principal.employee.id != employee.id:
        raise HTTPException(
            status_code=403,
            detail=(
                f"That token belongs to {principal.employee.name}, not to {employee.name}. "
                "An agent token can only act as its own agent."
            ),
        )
    principal.require(scope)
    return employee
