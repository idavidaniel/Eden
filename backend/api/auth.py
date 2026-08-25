"""Signing in, signing out, and the second factor.

Login is two steps when 2FA is on. The first step proves the password and hands
back a short-lived token that is good for exactly one thing: presenting a code.
It is not an access token and cannot be used as one — otherwise the second
factor would be advisory.

Tokens go into HTTP-only cookies. Script callers can read them from the response
body instead, but the browser never touches them from JavaScript, which is what
makes an XSS bug stop short of being a session theft.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config import get_settings
from db import get_db
from models import Tenant, User
from services import auth, totp

from .deps import UserPrincipal, current_user
from .limits import limiter

router = APIRouter(prefix="/auth", tags=["auth"])


class SignUpIn(BaseModel):
    email: str = Field(..., max_length=320)
    password: str = Field(..., max_length=200)
    full_name: str = Field(default="", max_length=160)
    organisation: str = Field(default="", max_length=160)


class LoginIn(BaseModel):
    email: str = Field(..., max_length=320)
    password: str = Field(..., max_length=200)


class SecondFactorIn(BaseModel):
    temporary_token: str
    code: str = Field(..., max_length=20)


class SetupConfirmIn(BaseModel):
    code: str = Field(..., max_length=20)


class DisableIn(BaseModel):
    password: str = Field(..., max_length=200)
    code: str = Field(..., max_length=20)


# --------------------------------------------------------------------------
# cookies
# --------------------------------------------------------------------------


def _set_session_cookies(response: Response, access: str, refresh: str) -> None:
    settings = get_settings()
    shared = {
        "httponly": True,
        "secure": settings.cookie_secure,
        # Lax, not Strict: Strict would drop the cookie when arriving from an
        # external link, which reads to the user as being randomly signed out.
        "samesite": "lax",
        "path": "/",
    }
    if settings.cookie_domain:
        shared["domain"] = settings.cookie_domain

    response.set_cookie(
        auth.ACCESS_COOKIE,
        access,
        max_age=settings.access_token_minutes * 60,
        **shared,
    )
    response.set_cookie(
        auth.REFRESH_COOKIE,
        refresh,
        max_age=settings.refresh_token_days * 24 * 3600,
        **shared,
    )


def _clear_session_cookies(response: Response) -> None:
    settings = get_settings()
    for name in (auth.ACCESS_COOKIE, auth.REFRESH_COOKIE):
        response.delete_cookie(
            name,
            path="/",
            domain=settings.cookie_domain or None,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
        )


def _session_payload(db: Session, user: User, response: Response, request: Request) -> dict:
    access = auth.mint_access_token(user)
    refresh = auth.issue_refresh_token(
        db,
        user,
        user_agent=request.headers.get("user-agent", ""),
        ip=_client_ip(request),
    )
    auth.note_signed_in(db, user)
    db.commit()
    _set_session_cookies(response, access, refresh)

    tenant = db.get(Tenant, user.tenant_id)
    return {
        "status": "signed_in",
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": get_settings().access_token_minutes * 60,
        "user": _me(user, tenant),
    }


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _me(user: User, tenant: Tenant | None) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "is_owner": user.is_owner,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "tenant": {
            "id": tenant.id if tenant else None,
            "name": tenant.name if tenant else None,
            "slug": tenant.slug if tenant else None,
        },
        "two_factor": totp.status(user),
    }


def _fail(exc: auth.AuthError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


# --------------------------------------------------------------------------
# signing up and in
# --------------------------------------------------------------------------


@router.post("/signup", status_code=201)
@limiter.limit(get_settings().signup_attempts_per_hour)
def sign_up(
    request: Request,
    response: Response,
    payload: SignUpIn,
    db: Session = Depends(get_db),
):
    """Create an account and the organisation it owns.

    One organisation per signup for now. Joining an existing one needs an
    invitation, and an invitation flow that nobody has designed yet would be
    worse than not having one.
    """
    try:
        user, _tenant = auth.sign_up(
            db,
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            organisation=payload.organisation,
        )
    except auth.AuthError as exc:
        raise _fail(exc) from exc
    return _session_payload(db, user, response, request)


@router.post("/login")
@limiter.limit(get_settings().login_attempts_per_minute)
def log_in(
    request: Request,
    response: Response,
    payload: LoginIn,
    db: Session = Depends(get_db),
):
    """Step one. With 2FA on, this proves the password and stops there."""
    try:
        user = auth.authenticate(db, email=payload.email, password=payload.password)
    except auth.AuthError as exc:
        raise _fail(exc) from exc

    if user.two_factor_enabled:
        db.commit()
        return {
            "status": "2fa_required",
            "requires_2fa": True,
            "temporary_token": auth.mint_two_factor_token(user),
            "expires_in": get_settings().two_factor_token_minutes * 60,
            "note": "Enter the code from your authenticator app, or a backup code.",
        }

    return {**_session_payload(db, user, response, request), "requires_2fa": False}


@router.post("/login/2fa")
@limiter.limit(get_settings().login_attempts_per_minute)
def log_in_second_factor(
    request: Request,
    response: Response,
    payload: SecondFactorIn,
    db: Session = Depends(get_db),
):
    """Step two. The temporary token alone is not enough to get in."""
    try:
        claims = auth.read_token(payload.temporary_token, expect="2fa")
    except auth.AuthError as exc:
        raise _fail(exc) from exc

    user = db.get(User, claims.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="That account is no longer active.")
    if not user.two_factor_enabled:
        raise HTTPException(
            status_code=400,
            detail="Two-factor is not on for this account. Sign in with your password.",
        )

    if not totp.verify_second_factor(db, user, payload.code):
        db.commit()
        raise HTTPException(
            status_code=401,
            detail="That code is not right. Codes last 30 seconds — check your phone's clock.",
        )
    return _session_payload(db, user, response, request)


@router.post("/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    """Trade a refresh token for a new pair. The old one stops working."""
    presented = request.cookies.get(auth.REFRESH_COOKIE) or _body_token(request)
    if not presented:
        raise HTTPException(status_code=401, detail="No refresh token was sent.")
    try:
        user, fresh = auth.rotate_refresh_token(
            db,
            presented,
            user_agent=request.headers.get("user-agent", ""),
            ip=_client_ip(request),
        )
    except auth.AuthError as exc:
        _clear_session_cookies(response)
        raise _fail(exc) from exc

    access = auth.mint_access_token(user)
    db.commit()
    _set_session_cookies(response, access, fresh)
    return {
        "status": "refreshed",
        "access_token": access,
        "refresh_token": fresh,
        "token_type": "bearer",
        "expires_in": get_settings().access_token_minutes * 60,
    }


def _body_token(request: Request) -> str | None:
    """A refresh token in the body, for callers that are not a browser."""
    header = request.headers.get("x-refresh-token", "")
    return header.strip() or None


@router.post("/logout")
def log_out(request: Request, response: Response, db: Session = Depends(get_db)):
    """Sign out here. The refresh token is revoked, not just forgotten."""
    presented = request.cookies.get(auth.REFRESH_COOKIE) or _body_token(request)
    revoked = auth.revoke_refresh_token(db, presented) if presented else False
    db.commit()
    _clear_session_cookies(response)
    return {"status": "signed_out", "revoked": revoked}


@router.post("/logout-everywhere")
def log_out_everywhere(
    response: Response,
    principal: UserPrincipal = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Sign out of every device. What you do after losing a laptop."""
    count = auth.revoke_all(db, principal.user, reason="signed out everywhere")
    db.commit()
    _clear_session_cookies(response)
    return {"status": "signed_out", "sessions_ended": count}


# --------------------------------------------------------------------------
# the second factor
# --------------------------------------------------------------------------


@router.post("/2fa/setup")
def start_two_factor(
    principal: UserPrincipal = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Generate a secret. Nothing is switched on until a code is confirmed."""
    try:
        result = totp.begin_setup(db, principal.user)
    except auth.AuthError as exc:
        raise _fail(exc) from exc
    db.commit()
    return result


@router.post("/2fa/verify-setup")
def confirm_two_factor(
    payload: SetupConfirmIn,
    principal: UserPrincipal = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Switch it on, and hand over the backup codes exactly once."""
    try:
        codes = totp.confirm_setup(db, principal.user, payload.code)
    except auth.AuthError as exc:
        raise _fail(exc) from exc
    db.commit()
    return {
        "status": "enabled",
        "backup_codes": codes,
        "note": (
            "Save these now — each works once, and they are the only way back in if you "
            "lose your phone. They are hashed here, so they cannot be shown again."
        ),
    }


@router.post("/2fa/disable")
def disable_two_factor(
    payload: DisableIn,
    principal: UserPrincipal = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Both the password and a current code. Being signed in is not enough."""
    user = principal.user
    if not user.two_factor_enabled:
        raise HTTPException(status_code=400, detail="Two-factor is not on.")
    if not auth.verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="That password is not right.")
    if not totp.verify_second_factor(db, user, payload.code):
        raise HTTPException(status_code=401, detail="That code is not right.")

    totp.disable(db, user)
    db.commit()
    return {"status": "disabled", "two_factor": totp.status(user)}


@router.post("/2fa/backup-codes")
def regenerate_backup_codes(
    payload: SetupConfirmIn,
    principal: UserPrincipal = Depends(current_user),
    db: Session = Depends(get_db),
):
    """A fresh set. The old ones stop working the moment these are issued."""
    user = principal.user
    if not user.two_factor_enabled:
        raise HTTPException(status_code=400, detail="Two-factor is not on.")
    if not totp.verify_code(user, payload.code):
        raise HTTPException(status_code=401, detail="That code is not right.")

    codes = [totp._new_backup_code() for _ in range(totp.BACKUP_CODE_COUNT)]
    user.backup_codes = [totp._hash_backup_code(code) for code in codes]
    db.add(user)
    db.commit()
    return {"backup_codes": codes, "note": "The previous set no longer works."}
