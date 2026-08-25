"""Signing in, and — the part that matters — not getting into anyone else's data."""

import uuid
from datetime import UTC, datetime, timedelta

import pyotp
import pytest

from db import session
from models import RefreshToken, User
from services import auth, crypto, totp

PASSWORD = "correct-horse-battery"


def _signup(client, email: str | None = None, **extra):
    address = email or f"p-{uuid.uuid4().hex[:10]}@example.com"
    response = client.post(
        "/auth/signup",
        json={"email": address, "password": PASSWORD, "full_name": "Test Person", **extra},
    )
    return address, response


def _user(email: str) -> User:
    db = session()
    try:
        return auth.find_user(db, email)
    finally:
        db.close()


# --------------------------------------------------------------------------
# signing up
# --------------------------------------------------------------------------


def test_signing_up_creates_an_account_and_the_organisation_it_owns(anonymous_client):
    email, response = _signup(anonymous_client, organisation="Marsh & Idris")
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["user"]["email"] == email
    assert body["user"]["is_owner"] is True
    assert body["user"]["tenant"]["name"] == "Marsh & Idris"
    assert body["access_token"] and body["refresh_token"]
    # And the session is set as cookies the browser will send back.
    assert anonymous_client.cookies.get("eden_access")
    assert anonymous_client.cookies.get("eden_refresh")


def test_the_password_is_never_stored_in_the_clear(anonymous_client):
    email, _ = _signup(anonymous_client)
    row = _user(email)
    assert PASSWORD not in row.hashed_password
    assert row.hashed_password.startswith("$2")  # bcrypt
    assert auth.verify_password(PASSWORD, row.hashed_password)
    assert not auth.verify_password("something else", row.hashed_password)


def test_the_same_email_cannot_sign_up_twice(anonymous_client):
    email, _ = _signup(anonymous_client)
    _, again = _signup(anonymous_client, email=email)
    assert again.status_code == 409
    assert "already an account" in again.json()["detail"]


@pytest.mark.parametrize("password", ["short", "12345678", ""])
def test_a_weak_password_is_refused_with_a_reason(anonymous_client, password):
    response = anonymous_client.post(
        "/auth/signup",
        json={"email": f"w-{uuid.uuid4().hex[:8]}@example.com", "password": password},
    )
    assert response.status_code == 400
    assert "at least" in response.json()["detail"]


def test_a_password_longer_than_bcrypt_reads_is_refused_not_truncated(anonymous_client):
    """Two different 100-character passwords must not be the same password."""
    response = anonymous_client.post(
        "/auth/signup",
        json={"email": f"l-{uuid.uuid4().hex[:8]}@example.com", "password": "x" * 100},
    )
    assert response.status_code == 400
    assert "as much as the hash reads" in response.json()["detail"]


def test_a_malformed_email_is_refused(anonymous_client):
    response = anonymous_client.post(
        "/auth/signup", json={"email": "notanemail", "password": PASSWORD}
    )
    assert response.status_code == 400


# --------------------------------------------------------------------------
# signing in
# --------------------------------------------------------------------------


def test_signing_in_with_the_right_password_works(anonymous_client):
    email, _ = _signup(anonymous_client)
    anonymous_client.cookies.clear()

    response = anonymous_client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "signed_in"
    assert body["requires_2fa"] is False
    assert anonymous_client.cookies.get("eden_access")


def test_the_wrong_password_says_nothing_useful(anonymous_client):
    email, _ = _signup(anonymous_client)
    response = anonymous_client.post("/auth/login", json={"email": email, "password": "nope"})
    assert response.status_code == 401
    # The same message whether or not the email exists.
    assert response.json()["detail"] == "That email and password do not match."

    unknown = anonymous_client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "nope"}
    )
    assert unknown.json()["detail"] == "That email and password do not match."


def test_enough_wrong_guesses_locks_the_account_for_a_while(anonymous_client):
    """The rate limit protects the endpoint; this protects one account."""
    email, _ = _signup(anonymous_client)
    for _ in range(8):
        anonymous_client.post("/auth/login", json={"email": email, "password": "nope"})

    blocked = anonymous_client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert blocked.status_code == 429
    assert "Too many failed attempts" in blocked.json()["detail"]

    # And it lifts, rather than locking somebody out forever.
    db = session()
    try:
        row = auth.find_user(db, email)
        row.locked_until = datetime.now(UTC) - timedelta(minutes=1)
        db.add(row)
        db.commit()
    finally:
        db.close()
    assert (
        anonymous_client.post(
            "/auth/login", json={"email": email, "password": PASSWORD}
        ).status_code
        == 200
    )


def test_a_deactivated_account_cannot_sign_in(anonymous_client):
    email, _ = _signup(anonymous_client)
    db = session()
    try:
        row = auth.find_user(db, email)
        row.is_active = False
        db.add(row)
        db.commit()
    finally:
        db.close()

    response = anonymous_client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 403


# --------------------------------------------------------------------------
# tokens
# --------------------------------------------------------------------------


def test_a_refresh_token_is_rotated_and_the_old_one_dies(anonymous_client):
    _signup(anonymous_client)
    first = anonymous_client.cookies.get("eden_refresh")

    refreshed = anonymous_client.post("/auth/refresh")
    assert refreshed.status_code == 200
    second = refreshed.json()["refresh_token"]
    assert second != first

    # Presenting the spent one is a replay, and takes every session with it.
    anonymous_client.cookies.set("eden_refresh", first)
    replayed = anonymous_client.post("/auth/refresh")
    assert replayed.status_code == 401
    assert "already been used" in replayed.json()["detail"]

    anonymous_client.cookies.set("eden_refresh", second)
    assert anonymous_client.post("/auth/refresh").status_code == 401


def test_a_refresh_token_is_not_stored_in_the_clear(anonymous_client):
    _signup(anonymous_client)
    presented = anonymous_client.cookies.get("eden_refresh")
    db = session()
    try:
        rows = list(db.query(RefreshToken).all())
        assert rows
        assert all(presented != row.digest for row in rows)
    finally:
        db.close()


def test_signing_out_actually_revokes_the_session(anonymous_client):
    _signup(anonymous_client)
    refresh = anonymous_client.cookies.get("eden_refresh")

    out = anonymous_client.post("/auth/logout")
    assert out.status_code == 200
    assert out.json()["revoked"] is True

    anonymous_client.cookies.set("eden_refresh", refresh)
    assert anonymous_client.post("/auth/refresh").status_code == 401


def test_an_access_token_expires(anonymous_client, monkeypatch):
    email, _ = _signup(anonymous_client)
    row = _user(email)

    import jwt as pyjwt

    stale = pyjwt.encode(
        {
            "sub": row.id,
            "tid": row.tenant_id,
            "typ": "access",
            "iat": datetime.now(UTC) - timedelta(hours=2),
            "exp": datetime.now(UTC) - timedelta(hours=1),
        },
        auth._secret(),
        algorithm=auth.ALGORITHM,
    )
    with pytest.raises(auth.AuthError) as caught:
        auth.read_token(stale)
    assert "expired" in str(caught.value)


def test_a_two_factor_token_cannot_be_used_as_an_access_token(anonymous_client):
    """Otherwise the second factor would be advisory."""
    email, _ = _signup(anonymous_client)
    row = _user(email)
    temporary = auth.mint_two_factor_token(row)

    with pytest.raises(auth.AuthError) as caught:
        auth.read_token(temporary, expect="access")
    assert "not a 'access' one" in str(caught.value) or "'2fa'" in str(caught.value)

    anonymous_client.cookies.clear()
    anonymous_client.cookies.set("eden_access", temporary)
    assert anonymous_client.get("/users/me").status_code == 401


# --------------------------------------------------------------------------
# the second factor
# --------------------------------------------------------------------------


def test_setting_up_two_factor_does_not_switch_it_on_until_a_code_works(client, account):
    """A mis-scanned QR code must not lock somebody out of their own account."""
    setup = client.post("/auth/2fa/setup").json()
    assert setup["secret"] and setup["uri"].startswith("otpauth://")

    assert client.get("/users/me/2fa").json()["enabled"] is False

    wrong = client.post("/auth/2fa/verify-setup", json={"code": "000000"})
    assert wrong.status_code == 400
    assert client.get("/users/me/2fa").json()["enabled"] is False

    right = client.post(
        "/auth/2fa/verify-setup", json={"code": pyotp.TOTP(setup["secret"]).now()}
    )
    assert right.status_code == 200
    assert len(right.json()["backup_codes"]) == totp.BACKUP_CODE_COUNT
    assert client.get("/users/me/2fa").json()["enabled"] is True


def test_the_totp_secret_is_sealed_at_rest(client, account):
    setup = client.post("/auth/2fa/setup").json()
    row = _user(account["email"])
    assert setup["secret"] not in (row.totp_secret_sealed or "")
    assert crypto.unseal(row.totp_secret_sealed) == setup["secret"]


def test_backup_codes_are_hashed_not_stored(client, account):
    setup = client.post("/auth/2fa/setup").json()
    codes = client.post(
        "/auth/2fa/verify-setup", json={"code": pyotp.TOTP(setup["secret"]).now()}
    ).json()["backup_codes"]

    row = _user(account["email"])
    assert all(code not in row.backup_codes for code in codes)
    assert len(row.backup_codes) == len(codes)


def test_login_becomes_two_steps_once_two_factor_is_on(client, account, anonymous_client):
    setup = client.post("/auth/2fa/setup").json()
    client.post("/auth/2fa/verify-setup", json={"code": pyotp.TOTP(setup["secret"]).now()})
    anonymous_client.cookies.clear()  # it signed this account up, so it holds a session

    first = anonymous_client.post(
        "/auth/login", json={"email": account["email"], "password": PASSWORD}
    )
    assert first.status_code == 200
    body = first.json()
    assert body["status"] == "2fa_required"
    assert body["requires_2fa"] is True
    assert "access_token" not in body
    assert not anonymous_client.cookies.get("eden_access")

    wrong = anonymous_client.post(
        "/auth/login/2fa",
        json={"temporary_token": body["temporary_token"], "code": "000000"},
    )
    assert wrong.status_code == 401

    second = anonymous_client.post(
        "/auth/login/2fa",
        json={
            "temporary_token": body["temporary_token"],
            "code": pyotp.TOTP(setup["secret"]).now(),
        },
    )
    assert second.status_code == 200
    assert second.json()["status"] == "signed_in"
    assert anonymous_client.cookies.get("eden_access")


def test_a_backup_code_works_once_and_only_once(client, account, anonymous_client):
    setup = client.post("/auth/2fa/setup").json()
    codes = client.post(
        "/auth/2fa/verify-setup", json={"code": pyotp.TOTP(setup["secret"]).now()}
    ).json()["backup_codes"]

    anonymous_client.cookies.clear()

    def sign_in_with(code: str):
        started = anonymous_client.post(
            "/auth/login", json={"email": account["email"], "password": PASSWORD}
        ).json()
        return anonymous_client.post(
            "/auth/login/2fa",
            json={"temporary_token": started["temporary_token"], "code": code},
        )

    assert sign_in_with(codes[0]).status_code == 200
    assert sign_in_with(codes[0]).status_code == 401, "a spent code must not work again"
    assert sign_in_with(codes[1]).status_code == 200

    assert _user(account["email"]).backup_codes.__len__() == len(codes) - 2


def test_disabling_two_factor_needs_the_password_and_a_code(client, account):
    setup = client.post("/auth/2fa/setup").json()
    client.post("/auth/2fa/verify-setup", json={"code": pyotp.TOTP(setup["secret"]).now()})

    assert (
        client.post(
            "/auth/2fa/disable",
            json={"password": "wrong", "code": pyotp.TOTP(setup["secret"]).now()},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/2fa/disable", json={"password": PASSWORD, "code": "000000"}
        ).status_code
        == 401
    )

    done = client.post(
        "/auth/2fa/disable",
        json={"password": PASSWORD, "code": pyotp.TOTP(setup["secret"]).now()},
    )
    assert done.status_code == 200
    row = _user(account["email"])
    assert row.two_factor_enabled is False
    assert row.totp_secret_sealed is None
    assert row.backup_codes == []


# --------------------------------------------------------------------------
# the profile
# --------------------------------------------------------------------------


def test_your_profile_is_yours(client, account):
    body = client.get("/users/me").json()
    assert body["email"] == account["email"]
    assert body["tenant"]["id"]
    assert body["two_factor"]["enabled"] is False
    assert "hashed_password" not in body

    client.patch("/users/me", json={"full_name": "Renamed Person"})
    assert client.get("/users/me").json()["full_name"] == "Renamed Person"


def test_changing_your_password_signs_your_other_devices_out(client, account, anonymous_client):
    other = anonymous_client.post(
        "/auth/login", json={"email": account["email"], "password": PASSWORD}
    )
    assert other.status_code == 200

    changed = client.post(
        "/users/me/password",
        json={"current_password": PASSWORD, "new_password": "a-whole-new-passphrase"},
    )
    assert changed.status_code == 200
    assert changed.json()["other_sessions_ended"] >= 1

    assert anonymous_client.post("/auth/refresh").status_code == 401


def test_the_current_password_is_required_to_change_it(client):
    response = client.post(
        "/users/me/password",
        json={"current_password": "not-it", "new_password": "a-whole-new-passphrase"},
    )
    assert response.status_code == 401


def test_signing_out_everywhere_ends_every_session(client, account, anonymous_client):
    anonymous_client.post("/auth/login", json={"email": account["email"], "password": PASSWORD})
    result = client.post("/auth/logout-everywhere")
    assert result.json()["sessions_ended"] >= 2
    assert anonymous_client.post("/auth/refresh").status_code == 401


# --------------------------------------------------------------------------
# who can reach what
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/companies"),
        ("get", "/users/me"),
        ("patch", "/users/me"),
        ("get", "/users/me/sessions"),
        ("post", "/auth/2fa/setup"),
        ("post", "/auth/logout-everywhere"),
    ],
)
def test_these_need_you_to_be_signed_in(anonymous_client, method, path):
    call = getattr(anonymous_client, method)
    response = call(path) if method == "get" else call(path, json={})
    assert response.status_code == 401, f"{path} answered {response.status_code}"


def test_the_health_check_stays_public(anonymous_client):
    """Something has to be able to tell whether the process is alive."""
    assert anonymous_client.get("/health").status_code == 200
