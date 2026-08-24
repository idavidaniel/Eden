"""Industry packs: what kind of company this is.

A pack is a YAML file describing the roles, the vocabulary for work, the shapes
of deliverable, and the checks that apply to each shape. It is loaded into rows
at company creation, so a company can be edited afterwards without editing the
file — the pack is a starting point, not a schema.

This is what makes "a law firm" a real answer rather than a renamed software team:
the roles differ, the work items differ, the deliverables differ, and above all
*the checks differ*, so the platform still refuses to take anyone's word for it.
"""

import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from models import ArtifactKind, Check, Company, Role
from models.work import CHECK_KINDS

log = logging.getLogger(__name__)

PACKS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packs")
DEFAULT_PACK = "software_studio"

# Capabilities the platform understands, with the label the interface shows.
# Packs may introduce their own; these are the ones the runtime reasons about.
CAPABILITY_LABELS = {
    "plan": "Plan and break down work",
    "delegate": "Assign work to others",
    "approve": "Sign off on work",
    "review": "Review someone else's work",
    "write_code": "Write and run code",
    "write_document": "Write prose documents",
    "write_copy": "Write marketing copy",
    "draft_document": "Draft formal documents",
    "legal_research": "Research points of law",
    "cite_check": "Verify citations",
    "prepare_filing": "Prepare filings",
    "research": "Research using sources",
    "analyse": "Analyse data",
    "design": "Design interfaces or assets",
    "specify": "Write requirements",
    "prioritise": "Decide what comes first",
    "test": "Test and verify",
    "debug": "Diagnose failures",
    "deploy": "Package and deploy",
    "client_comms": "Talk to the client",
    "report": "Report on progress",
}


class PackError(RuntimeError):
    pass


@dataclass(frozen=True)
class PackRole:
    key: str
    title: str
    department: str = "General"
    avatar: str = "🤖"
    summary: str = ""
    persona: str = ""
    skills: list[str] = field(default_factory=list)
    toolbelt: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    manages: bool = False
    position: int = 100


@dataclass(frozen=True)
class Pack:
    key: str
    name: str
    tagline: str
    description: str
    departments: list[str]
    work_item_kinds: list[str]
    default_team: list[str]
    roles: list[PackRole]
    artifact_kinds: list[dict]
    checks: list[dict]
    handbook: str

    def role(self, key: str) -> PackRole | None:
        return next((role for role in self.roles if role.key == key), None)


def _coerce(raw: dict, path: str) -> Pack:
    missing = [field_name for field_name in ("key", "name") if not raw.get(field_name)]
    if missing:
        raise PackError(f"{path} is missing {', '.join(missing)}")

    roles = []
    for item in raw.get("roles") or []:
        if not item.get("key") or not item.get("title"):
            raise PackError(f"{path}: every role needs a key and a title")
        roles.append(
            PackRole(
                key=item["key"],
                title=item["title"],
                department=item.get("department", "General"),
                avatar=item.get("avatar", "🤖"),
                summary=(item.get("summary") or "").strip(),
                persona=(item.get("persona") or "").strip(),
                skills=list(item.get("skills") or []),
                toolbelt=list(item.get("toolbelt") or []),
                capabilities=list(item.get("capabilities") or []),
                keywords=list(item.get("keywords") or []),
                manages=bool(item.get("manages")),
                position=int(item.get("position", 100)),
            )
        )

    for check in raw.get("checks") or []:
        if check.get("kind") not in CHECK_KINDS:
            raise PackError(
                f"{path}: check '{check.get('key')}' has kind '{check.get('kind')}'. "
                f"Use one of: {', '.join(CHECK_KINDS)}"
            )

    known_checks = {check["key"] for check in raw.get("checks") or []}
    for kind in raw.get("artifact_kinds") or []:
        for check_key in kind.get("default_checks") or []:
            if check_key not in known_checks:
                raise PackError(
                    f"{path}: artifact kind '{kind.get('key')}' wants check "
                    f"'{check_key}', which the pack does not define"
                )

    return Pack(
        key=raw["key"],
        name=raw["name"],
        tagline=(raw.get("tagline") or "").strip(),
        description=(raw.get("description") or "").strip(),
        departments=list(raw.get("departments") or ["General"]),
        work_item_kinds=list(raw.get("work_item_kinds") or ["task"]),
        default_team=list(raw.get("default_team") or []),
        roles=roles,
        artifact_kinds=list(raw.get("artifact_kinds") or []),
        checks=list(raw.get("checks") or []),
        handbook=(raw.get("handbook") or "").strip(),
    )


@lru_cache
def all_packs() -> dict[str, Pack]:
    packs: dict[str, Pack] = {}
    if not os.path.isdir(PACKS_DIR):
        log.warning("No packs directory at %s", PACKS_DIR)
        return packs
    for name in sorted(os.listdir(PACKS_DIR)):
        if not name.endswith((".yaml", ".yml")):
            continue
        path = os.path.join(PACKS_DIR, name)
        with open(path) as handle:
            raw = yaml.safe_load(handle) or {}
        pack = _coerce(raw, path)
        packs[pack.key] = pack
    return packs


def get_pack(key: str | None) -> Pack:
    """The pack by that name. No key means the default; a wrong key is an error.

    Quietly substituting the default for a name nobody has would found a
    software studio for someone who asked for a law firm, and they would not
    find out until the wrong people showed up.
    """
    packs = all_packs()
    if key:
        if key in packs:
            return packs[key]
        raise PackError(
            f"There is no industry pack called '{key}'. "
            f"Installed: {', '.join(sorted(packs)) or 'none'}."
        )
    if DEFAULT_PACK in packs:
        return packs[DEFAULT_PACK]
    raise PackError(f"No industry packs are installed in {PACKS_DIR}")


def list_packs() -> list[Pack]:
    return sorted(all_packs().values(), key=lambda pack: (pack.key != DEFAULT_PACK, pack.name))


# --------------------------------------------------------------------------
# applying a pack to a company
# --------------------------------------------------------------------------


def apply_pack(db: Session, company: Company, pack_key: str | None = None) -> Pack:
    """Write a pack's roles, artifact kinds and checks into a company.

    Idempotent: existing rows are updated in place rather than duplicated, so
    re-applying a pack after editing the YAML refreshes without wiping overrides
    that share a key.
    """
    pack = get_pack(pack_key or company.pack_key)

    company.pack_key = pack.key
    company.departments = list(pack.departments)
    company.work_item_kinds = list(pack.work_item_kinds)
    if not company.handbook and pack.handbook:
        company.handbook = pack.handbook
    if not company.industry:
        company.industry = pack.name
    db.add(company)

    existing_roles = {
        row.key: row for row in db.scalars(select(Role).where(Role.company_id == company.id))
    }
    for role in pack.roles:
        row = existing_roles.get(role.key) or Role(company_id=company.id, key=role.key)
        row.title = role.title
        row.department = role.department
        row.avatar = role.avatar
        row.summary = role.summary
        row.persona = role.persona
        row.skills = list(role.skills)
        row.toolbelt = list(role.toolbelt)
        row.capabilities = list(role.capabilities)
        row.keywords = list(role.keywords)
        row.manages = role.manages
        row.position = role.position
        db.add(row)

    existing_kinds = {
        row.key: row
        for row in db.scalars(select(ArtifactKind).where(ArtifactKind.company_id == company.id))
    }
    for kind in pack.artifact_kinds:
        row = existing_kinds.get(kind["key"]) or ArtifactKind(
            company_id=company.id, key=kind["key"]
        )
        row.name = kind.get("name", kind["key"])
        row.storage = kind.get("storage", "blob")
        row.renderer = kind.get("renderer", "document")
        row.default_checks = list(kind.get("default_checks") or [])
        row.description = (kind.get("description") or "").strip()[:300]
        db.add(row)

    # Company-level checks: no project, no work item, optionally bound to an
    # artifact kind. Project checks are created from these when work starts.
    existing_checks = {
        row.key: row
        for row in db.scalars(
            select(Check).where(
                Check.company_id == company.id,
                Check.project_id.is_(None),
                Check.work_item_id.is_(None),
            )
        )
    }
    binding = {
        check_key: kind["key"]
        for kind in pack.artifact_kinds
        for check_key in (kind.get("default_checks") or [])
    }
    for position, check in enumerate(pack.checks):
        row = existing_checks.get(check["key"]) or Check(
            company_id=company.id, key=check["key"], created_by="Pack"
        )
        row.name = check.get("name", check["key"])
        row.kind = check["kind"]
        row.spec = dict(check.get("spec") or {})
        row.required = bool(check.get("required", True))
        row.artifact_kind = binding.get(check["key"])
        row.position = position
        db.add(row)

    db.flush()
    return pack


def kinds_for(company: Company) -> list[str]:
    """The vocabulary this company uses for work items."""
    return list(company.work_item_kinds or get_pack(company.pack_key).work_item_kinds)


def artifact_kinds_for(db: Session, company: Company) -> list[ArtifactKind]:
    rows = list(
        db.scalars(
            select(ArtifactKind)
            .where(ArtifactKind.company_id == company.id)
            .order_by(ArtifactKind.name)
        )
    )
    if rows:
        return rows
    apply_pack(db, company)
    return list(
        db.scalars(
            select(ArtifactKind)
            .where(ArtifactKind.company_id == company.id)
            .order_by(ArtifactKind.name)
        )
    )
