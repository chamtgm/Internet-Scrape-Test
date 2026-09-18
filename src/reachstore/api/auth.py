"""The boundary between a request and an identity.

This module is the only place a cookie becomes a `User`, and the only place
that writes SQL against `users`, `sessions`, or `invites`. Same discipline as
`query.visible_to` being the sole tenant predicate: one function to audit.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from reachstore.api.deps import get_session
from reachstore.models import Invite, User, UserSession

COOKIE_NAME = "reachstore_session"
SESSION_LIFETIME = timedelta(days=30)
INVITE_LIFETIME = timedelta(days=7)
MIN_PASSWORD_LENGTH = 8

# scrypt parameters. Measured at 41 ms on the development machine: slow enough
# that offline brute force is expensive, fast enough that a login feels
# instant. `maxmem` is derived from the stored parameters rather than fixed, so
# raising the cost later does not silently invalidate every existing password.
_N = 2**15
_R = 8
_P = 1
_DKLEN = 64


def _maxmem(n: int, r: int) -> int:
    return 128 * n * r * 2


def hash_password(password: str) -> str:
    """Encode as `scrypt$n$r$p$<b64 salt>$<b64 digest>`.

    The salt is random per password, so two identical passwords do not produce
    identical hashes and a stolen dump cannot be attacked by grouping equal
    rows.
    """
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=_N,
        r=_R,
        p=_P,
        maxmem=_maxmem(_N, _R),
        dklen=_DKLEN,
    )
    return "scrypt${}${}${}${}${}".format(
        _N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(dk).decode()
    )


def verify_password(password: str, encoded: str) -> bool:
    """False for anything that is not a valid matching hash. Never raises for
    malformed input -- but a genuine scrypt fault (e.g. `maxmem` wrong for a
    raised cost setting) is allowed to raise rather than being swallowed as
    a false "wrong password": only the parsing of `encoded` sits inside the
    `try`, not the `hashlib.scrypt` call itself.

    `users.password_hash` defaults to "" and one such row already exists
    (`hand-verify@example.com`, left over from Plan 1 hand-verification).
    Returning False for an empty or malformed value is what makes such a row
    unable to authenticate -- without a migration special case, and without a
    condition that has to be remembered at every query.
    """
    try:
        scheme, n, r, p, salt_b64, dk_b64 = encoded.split("$")
        if scheme != "scrypt":
            return False
        n_i, r_i, p_i = int(n), int(r), int(p)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
    except (AttributeError, ValueError, TypeError):
        return False
    dk = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=n_i,
        r=r_i,
        p=p_i,
        maxmem=_maxmem(n_i, r_i),
        dklen=len(expected),
    )
    return secrets.compare_digest(dk, expected)


_DUMMY: str | None = None


def spend_dummy_verify() -> None:
    """Burn the same CPU a real verification would.

    Called on the unknown-email branch of login. Without it, an unknown
    address returns measurably faster than a known one with a wrong password,
    which turns response latency into a user-enumeration oracle.
    """
    global _DUMMY
    if _DUMMY is None:
        # Generating the dummy hash already costs one scrypt call -- the same
        # cost `verify_password` pays below on every later call. Also calling
        # `verify_password` here would charge the very first unknown-email
        # login for two scrypt calls instead of one.
        _DUMMY = hash_password(secrets.token_urlsafe(16))
        return
    verify_password("x", _DUMMY)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_email(email: str) -> str:
    """The canonical form of an address: stripped and lowercased.

    Applied everywhere an email enters or is looked up, so `Alice@Example.com`
    and `alice@example.com` are one account. Not a security measure -- invites
    come from someone with shell access -- but a lockout that cannot be
    diagnosed: the invitee never types their address during setup, so they
    never learn which case the operator used, and login deliberately answers a
    wrong password and an unknown email identically. Without this, a
    case-mismatched login is indistinguishable from a wrong password to the
    person locked out and to the operator both.
    """
    return email.strip().lower()


def create_session(session: Session, *, user_id: int, now: datetime) -> str:
    """Issue a session and return the RAW token -- the only time it exists.

    Only its SHA-256 digest is stored, so a database dump contains no usable
    sessions.
    """
    token = secrets.token_urlsafe(32)
    session.add(
        UserSession(
            user_id=user_id,
            token_hash=_digest(token),
            created_at=now,
            expires_at=now + SESSION_LIFETIME,
        )
    )
    session.flush()
    return token


def lookup_session(session: Session, *, token: str, now: datetime) -> User | None:
    """The user for this token, or None.

    A pure read. An expired row is left in place rather than deleted here:
    `deps.get_session` only closes (and therefore rolls back) after a
    request, it never commits, so a delete issued from this read path would
    never persist anyway. The row is simply inert -- this check re-runs on
    every lookup, so an expired row can never grant access. Reclaiming
    expired rows is a separate concern (a periodic sweep) if the table ever
    grows enough to matter; at a handful of users with 30-day sessions the
    volume is negligible.
    """
    row = (
        session.execute(
            select(UserSession).where(UserSession.token_hash == _digest(token))
        )
        .scalars()
        .one_or_none()
    )
    if row is None or row.expires_at <= now:
        return None
    return session.get(User, row.user_id)


def delete_session(session: Session, *, token: str) -> None:
    session.execute(delete(UserSession).where(UserSession.token_hash == _digest(token)))


def delete_all_sessions(session: Session, *, user_id: int) -> int:
    """Revoke every session for one user. Returns how many were removed."""
    result = session.execute(delete(UserSession).where(UserSession.user_id == user_id))
    return result.rowcount or 0


def create_invite(
    session: Session, *, email: str, display_name: str, is_admin: bool, now: datetime
) -> str:
    """Issue an invite and return the RAW token -- the only time it exists."""
    token = secrets.token_urlsafe(32)
    session.add(
        Invite(
            email=normalize_email(email),
            display_name=display_name,
            is_admin=is_admin,
            token_hash=_digest(token),
            created_at=now,
            expires_at=now + INVITE_LIFETIME,
        )
    )
    session.flush()
    return token


def consume_invite(session: Session, *, token: str, now: datetime) -> Invite | None:
    """Mark an invite spent and return it, or None if unusable."""
    row = (
        session.execute(select(Invite).where(Invite.token_hash == _digest(token)))
        .scalars()
        .one_or_none()
    )
    if row is None or row.consumed_at is not None or row.expires_at <= now:
        return None
    row.consumed_at = now
    session.flush()
    return row


def find_user_by_email(session: Session, email: str) -> User | None:
    """The user with this email, or None.

    Used by login now; the invite-setup and password-reset flows (Tasks 6-7)
    need the same lookup, so it lives here rather than being duplicated --
    `auth.py` already owns every query against `users`. Normalising here rather
    than at each caller is what makes login, `invite`'s duplicate check,
    `set-password`, and `revoke-sessions` all case-insensitive at once.
    """
    stmt = select(User).where(User.email == normalize_email(email))
    return session.execute(stmt).scalars().one_or_none()


def get_current_user(
    session: Session = Depends(get_session),
    token: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> User:
    """The authenticated user, or 401.

    `alias=COOKIE_NAME` binds this parameter to the `reachstore_session`
    cookie regardless of what the Python parameter is named. Relying on the
    parameter name matching the cookie name instead is a silent footgun --
    verified experimentally: FastAPI reads `None` with no error if they ever
    drift apart.
    """
    if token is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    user = lookup_session(session, token=token, now=datetime.now(UTC))
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="admin only")
    return user
