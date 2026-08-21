"""Issues each AI employee their own accounts: username, password, API token."""

import re
import unicodedata

from sqlalchemy.orm import Session

from models import Employee, Identity

from .crypto import generate_password, generate_token, hash_secret, seal, unseal


def slugify(value: str, fallback: str = "item") -> str:
    normalised = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalised.lower()).strip("-")
    return slug or fallback


def username_for(employee: Employee, tool: str, company_slug: str) -> str:
    return f"{slugify(employee.name, 'agent')}@{company_slug}.{tool}"


def provision(
    db: Session, employee: Employee, company_slug: str, tools: list[str]
) -> list[Identity]:
    """Create one service account per tool the employee is issued."""
    existing = {identity.tool for identity in employee.identities}
    created = []
    for tool in tools:
        if tool in existing:
            continue
        password = generate_password()
        token = generate_token(tool[:4])
        identity = Identity(
            employee_id=employee.id,
            tool=tool,
            username=username_for(employee, tool, company_slug),
            password_hash=hash_secret(password),
            password_sealed=seal(password),
            token_hash=hash_secret(token),
            token_sealed=seal(token),
        )
        db.add(identity)
        created.append(identity)
    return created


def revoke(db: Session, identity: Identity) -> Identity:
    """Rotate an account's password and token in place."""
    password, token = generate_password(), generate_token(identity.tool[:4])
    identity.password_hash = hash_secret(password)
    identity.password_sealed = seal(password)
    identity.token_hash = hash_secret(token)
    identity.token_sealed = seal(token)
    db.add(identity)
    return identity


def reveal(identity: Identity) -> dict:
    return {
        "tool": identity.tool,
        "username": identity.username,
        "password": unseal(identity.password_sealed),
        "token": unseal(identity.token_sealed),
    }
