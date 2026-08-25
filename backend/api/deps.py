"""Who is calling, and what they are allowed to touch.

Three kinds of caller, and the difference matters:

  * a **person**, holding an access token in an HTTP-only cookie (or a bearer
    header, for a script). They act on behalf of a tenant;
  * an **agent**, holding a token that belongs to exactly one employee. It can
    only ever act as that employee, and its tenant is derived from the company
    that employee works for;
  * nobody, which is not a caller. Every route that reads company data requires
    one of the first two.

`tenant_of` is the load-bearing function here. A company is not reachable just
because its id is known — it has to belong to the caller's tenant. Without that
check the sign-in screen would be decoration, which is the usual way multi-user
software turns out not to be multi-user at all.
"""

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from db import get_db
from models import AgentToken, Company, Employee, Tenant, User
from services import auth, tokens


@dataclass
class AgentPrincipal:
    token: AgentToken
    employee: Employee
    company: Company

    @property
    def tenant_id(self) -> str:
        return self.company.tenant_id

    def require(self, scope: str) -> None:
        if not tokens.has_scope(self.token, scope):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"This token does not carry the '{scope}' scope. "
                    f"It has: {', '.join(self.token.scopes or []) or 'nothing'}."
                ),
            )


@dataclass
class UserPrincipal:
    user: User
    tenant: Tenant

    @property
    def tenant_id(self) -> str:
        return self.user.tenant_id


# --------------------------------------------------------------------------
# reading credentials off a request
# --------------------------------------------------------------------------


def _bearer(request: Request, authorization: str | None) -> str | None:
    header = authorization or request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def _access_token(request: Request, authorization: str | None) -> str | None:
    """The cookie first, because that is how the browser talks to us.

    A bearer header is accepted too, so a script does not need a cookie jar —
    but an agent token also arrives as a bearer header, so whichever is read
    here must be validated as the kind it claims to be.
    """
    cookie = request.cookies.get(auth.ACCESS_COOKIE)
    if cookie:
        return cookie
    return _bearer(request, authorization)


def optional_user(
    request: Request,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> UserPrincipal | None:
    presented = _access_token(request, authorization)
    if not presented:
        return None
    try:
        claims = auth.read_token(presented, expect="access")
    except auth.AuthError:
        return None
    user = db.get(User, claims.user_id)
    if not user or not user.is_active:
        return None
    tenant = db.get(Tenant, user.tenant_id)
    if not tenant:
        return None
    return UserPrincipal(user=user, tenant=tenant)


def current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> UserPrincipal:
    presented = _access_token(request, authorization)
    if not presented:
        raise HTTPException(
            status_code=401,
            detail="Sign in first.",
            headers={"WWW-Authenticate": 'Bearer realm="eden"'},
        )
    try:
        claims = auth.read_token(presented, expect="access")
    except auth.AuthError as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
            headers={"WWW-Authenticate": 'Bearer realm="eden"'},
        ) from exc

    user = db.get(User, claims.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="That account no longer exists.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="That account has been deactivated.")
    tenant = db.get(Tenant, user.tenant_id)
    if not tenant:
        raise HTTPException(status_code=403, detail="That account has no organisation.")
    return UserPrincipal(user=user, tenant=tenant)


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


# --------------------------------------------------------------------------
# either kind of caller
# --------------------------------------------------------------------------


@dataclass
class Caller:
    """Whoever is asking, with the one thing every route needs: their tenant."""

    tenant_id: str
    user: UserPrincipal | None = None
    agent: AgentPrincipal | None = None

    @property
    def label(self) -> str:
        if self.user:
            return self.user.user.full_name or self.user.user.email
        if self.agent:
            return f"{self.agent.employee.name} ({self.agent.employee.title})"
        return "Unknown"

    @property
    def is_person(self) -> bool:
        return self.user is not None


def current_caller(
    request: Request,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Caller:
    """A person or an agent. Anonymous is not a caller."""
    person = optional_user(request, authorization, db)
    if person:
        return Caller(tenant_id=person.tenant_id, user=person)

    agent = optional_agent(request, authorization, db)
    if agent:
        return Caller(tenant_id=agent.tenant_id, agent=agent)

    raise HTTPException(
        status_code=401,
        detail="Sign in, or send an agent token.",
        headers={"WWW-Authenticate": 'Bearer realm="eden"'},
    )


# --------------------------------------------------------------------------
# scoping
# --------------------------------------------------------------------------


def company_for(db: Session, company_id: str, caller: Caller) -> Company:
    """The company, if it is the caller's to see.

    404 rather than 403 for another tenant's company: answering "that exists but
    is not yours" would turn this endpoint into a way to enumerate other
    people's companies.
    """
    company = db.get(Company, company_id)
    if not company or company.tenant_id != caller.tenant_id:
        raise HTTPException(status_code=404, detail="Company not found.")
    if caller.agent and caller.agent.company.id != company.id:
        raise HTTPException(
            status_code=403,
            detail="That token belongs to an employee of a different company.",
        )
    return company


def get_employee(db: Session, employee_id: str) -> Employee:
    """An employee, if their company belongs to whoever is asking.

    Every `/agents/{id}/…` route goes through here, including the one that mints
    tokens — so an unscoped version of this would let anyone who knows a UUID
    issue themselves a working credential for somebody else's agent. That is the
    single worst thing this system could get wrong.
    """
    from .scope import require_caller

    who = require_caller()
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found.")
    company = db.get(Company, employee.company_id)
    if not company or company.tenant_id != who.tenant_id:
        raise HTTPException(status_code=404, detail="Employee not found.")
    return employee


def employee_for(db: Session, employee_id: str, caller: Caller) -> Employee:
    employee = get_employee(db, employee_id)
    if employee.company.tenant_id != caller.tenant_id:
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
