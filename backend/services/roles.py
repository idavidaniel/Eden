"""Roles, as data belonging to a company rather than a hardcoded catalogue.

A role used to be one of nine software jobs compiled into this module. It is a
row now, seeded from the company's industry pack, so a law firm gets partners and
a research lab gets a principal investigator. Everything here reads the rows and
falls back to the pack file when a company has none yet — which is what keeps
companies created before packs existed working unchanged.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Company, Employee, Role

from . import packs

# Tool groups a company can issue accounts for.
TOOLS = ["workspace", "tracker", "wiki", "chat", "documents", "research", "data"]


def ensure_roles(db: Session, company: Company) -> list[Role]:
    """Every company has roles; create them from its pack the first time."""
    rows = list(
        db.scalars(
            select(Role).where(Role.company_id == company.id).order_by(Role.position, Role.title)
        )
    )
    if rows:
        return rows
    packs.apply_pack(db, company)
    return list(
        db.scalars(
            select(Role).where(Role.company_id == company.id).order_by(Role.position, Role.title)
        )
    )


def list_roles(db: Session, company: Company) -> list[Role]:
    return ensure_roles(db, company)


def get_role(db: Session, company: Company, key: str) -> Role:
    """The named role, or the company's most general one."""
    rows = ensure_roles(db, company)
    exact = next((row for row in rows if row.key == key), None)
    if exact:
        return exact
    fallback = next((row for row in rows if not row.manages), None)
    return fallback or rows[0]


def default_team(company: Company) -> list[str]:
    return list(packs.get_pack(company.pack_key).default_team)


def match_role(db: Session, company: Company, text: str) -> str:
    """Best-effort mapping of free text ('draft the NDA') to a role key."""
    lowered = (text or "").lower()
    best, best_score = None, 0
    for role in ensure_roles(db, company):
        score = sum(1 for keyword in role.keywords or [] if keyword in lowered)
        score += sum(1 for capability in role.capabilities or [] if capability in lowered)
        if role.key.replace("_", " ") in lowered or role.title.lower() in lowered:
            score += 3
        if score > best_score:
            best, best_score = role.key, score
    if best:
        return best
    doer = next((role for role in ensure_roles(db, company) if not role.manages), None)
    return doer.key if doer else ensure_roles(db, company)[0].key


def manager_of(db: Session, team: list[Employee], company: Company) -> Employee | None:
    """Whoever runs this team, by their role's `manages` flag."""
    managing = {role.key for role in ensure_roles(db, company) if role.manages}
    return next((person for person in team if person.role_key in managing), None)


def capabilities_of(db: Session, employee: Employee, company: Company) -> list[str]:
    """What this person can be asked to do — their own list, or their role's."""
    if employee.capabilities:
        return list(employee.capabilities)
    return list(get_role(db, company, employee.role_key).capabilities or [])


def pick_for(
    db: Session,
    company: Company,
    team: list[Employee],
    *,
    capability: str | None = None,
    role_key: str | None = None,
) -> Employee | None:
    """Choose who does a piece of work.

    Capability first, role second, department third. Assigning on capability is
    what lets a planner staff a matter in a law firm without knowing that
    `associate` is the name of the job that drafts things.
    """
    if not team:
        return None

    if capability:
        able = [
            person
            for person in team
            if capability in capabilities_of(db, person, company)
            and not get_role(db, company, person.role_key).manages
        ]
        if able:
            return _least_busy(able)
        able_including_managers = [
            person for person in team if capability in capabilities_of(db, person, company)
        ]
        if able_including_managers:
            return _least_busy(able_including_managers)

    if role_key:
        exact = [person for person in team if person.role_key == role_key]
        if exact:
            return _least_busy(exact)
        role = get_role(db, company, role_key)
        same_department = [
            person
            for person in team
            if person.department == role.department
            and not get_role(db, company, person.role_key).manages
        ]
        if same_department:
            return _least_busy(same_department)

    doers = [person for person in team if not get_role(db, company, person.role_key).manages]
    return _least_busy(doers) if doers else team[0]


def _least_busy(people: list[Employee]) -> Employee:
    """Spread work rather than piling it on whoever appears first."""
    return sorted(people, key=lambda person: (person.status == "working", person.name))[0]
