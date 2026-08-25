"""Your own account. Nobody else's.

There is no `GET /users/{id}`: every route here reads the caller's identity from
their token rather than from the path, so there is no id to tamper with.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db import get_db
from models import Company, RefreshToken
from services import auth, totp

from .auth import _me
from .deps import UserPrincipal, current_user

router = APIRouter(tags=["users"])


class ProfilePatch(BaseModel):
    full_name: str | None = Field(default=None, max_length=160)


class PasswordChange(BaseModel):
    current_password: str = Field(..., max_length=200)
    new_password: str = Field(..., max_length=200)


@router.get("/users/me")
def read_me(
    principal: UserPrincipal = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Your profile, your organisation, and the state of your second factor."""
    companies = db.scalar(
        select(func.count())
        .select_from(Company)
        .where(Company.tenant_id == principal.tenant_id)
    )
    sessions = db.scalar(
        select(func.count())
        .select_from(RefreshToken)
        .where(
            RefreshToken.user_id == principal.user.id,
            RefreshToken.revoked_at.is_(None),
        )
    )
    return {
        **_me(principal.user, principal.tenant),
        "companies": companies or 0,
        "active_sessions": sessions or 0,
    }


@router.patch("/users/me")
def update_me(
    payload: ProfilePatch,
    principal: UserPrincipal = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Change your name.

    Not your email: changing it has to prove the new address is yours, and an
    email change that skips verification is an account takeover waiting for
    somebody to leave a laptop unlocked.
    """
    changes = payload.model_dump(exclude_unset=True)
    if "full_name" in changes:
        principal.user.full_name = (changes["full_name"] or "").strip()[:160]
    db.add(principal.user)
    db.commit()
    return _me(principal.user, principal.tenant)


@router.post("/users/me/password")
def change_password(
    payload: PasswordChange,
    principal: UserPrincipal = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Change your password, and sign every other device out.

    A password change usually means "somebody might have had this". Leaving
    other sessions alive would defeat the point.
    """
    user = principal.user
    if not auth.verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=401, detail="That is not your current password.")
    try:
        user.hashed_password = auth.hash_password(payload.new_password)
    except auth.AuthError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    db.add(user)
    ended = auth.revoke_all(db, user, reason="password changed")
    db.commit()
    return {
        "status": "changed",
        "other_sessions_ended": max(0, ended),
        "note": "You will need to sign in again on your other devices.",
    }


@router.get("/users/me/sessions")
def list_sessions(
    principal: UserPrincipal = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Where you are signed in. Useful when something feels wrong."""
    rows = list(
        db.scalars(
            select(RefreshToken)
            .where(
                RefreshToken.user_id == principal.user.id,
                RefreshToken.revoked_at.is_(None),
            )
            .order_by(RefreshToken.created_at.desc())
            .limit(50)
        )
    )
    return [
        {
            "id": row.id,
            "user_agent": row.user_agent,
            "ip": row.ip,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        }
        for row in rows
    ]


@router.get("/users/me/2fa")
def two_factor_status(principal: UserPrincipal = Depends(current_user)):
    return totp.status(principal.user)
