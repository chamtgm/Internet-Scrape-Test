from datetime import UTC, datetime, timedelta

import pytest

from reachstore.api import auth
from reachstore.models import Invite, User, UserSession

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


def make_user(session, *, email="a@example.test", is_admin=False, password=None):
    user = User(
        email=email,
        display_name="A",
        password_hash=auth.hash_password(password) if password else "",
        is_admin=is_admin,
        created_at=NOW,
    )
    session.add(user)
    session.flush()
    return user


# --- passwords ---------------------------------------------------------------

def test_password_round_trip():
    encoded = auth.hash_password("correct horse battery staple")
    assert auth.verify_password("correct horse battery staple", encoded)


def test_wrong_password_rejected():
    encoded = auth.hash_password("right")
    assert not auth.verify_password("wrong", encoded)


def test_same_password_hashes_differently_each_time():
    """A per-password random salt means two identical passwords do not collide,
    so a stolen dump cannot be attacked by grouping equal hashes."""
    a = auth.hash_password("same")
    b = auth.hash_password("same")
    assert a != b
    assert auth.verify_password("same", a)
    assert auth.verify_password("same", b)


@pytest.mark.parametrize(
    "encoded",
    [
        "",                      # the pre-existing hand-verify row
        "not-a-hash",
        "scrypt$only$three$parts",
        "bcrypt$1$2$3$4$5",      # wrong scheme
        "scrypt$x$8$1$AAAA$BBBB",  # non-numeric cost parameter
    ],
)
def test_malformed_or_empty_hash_is_rejected_without_raising(encoded):
    """`users.password_hash` defaults to "" and one such row already exists.
    Returning False here is what makes it unable to authenticate -- no
    migration special case, no condition spread across queries."""
    assert auth.verify_password("anything", encoded) is False


def test_tampered_digest_rejected():
    encoded = auth.hash_password("secret")
    scheme, n, r, p, salt, dk = encoded.split("$")
    flipped = ("A" if dk[0] != "A" else "B") + dk[1:]
    assert not auth.verify_password("secret", "$".join([scheme, n, r, p, salt, flipped]))


# --- sessions ----------------------------------------------------------------

def test_create_then_lookup_returns_the_user(session):
    user = make_user(session)
    token = auth.create_session(session, user_id=user.id, now=NOW)
    found = auth.lookup_session(session, token=token, now=NOW)
    assert found is not None and found.id == user.id


def test_raw_token_is_not_stored(session):
    """Only the digest is persisted, so a dump yields no usable sessions."""
    from sqlalchemy import select

    user = make_user(session)
    token = auth.create_session(session, user_id=user.id, now=NOW)
    stored = session.execute(select(UserSession.token_hash)).scalars().all()
    assert token not in stored
    assert len(stored[0]) == 64


def test_unknown_token_returns_none(session):
    assert auth.lookup_session(session, token="nope", now=NOW) is None


def test_expired_session_is_rejected_and_deleted(session):
    """Deleting on the way past means expiry needs no scheduler."""
    from sqlalchemy import func, select

    user = make_user(session)
    token = auth.create_session(session, user_id=user.id, now=NOW)
    later = NOW + auth.SESSION_LIFETIME + timedelta(seconds=1)

    assert auth.lookup_session(session, token=token, now=later) is None
    assert session.execute(select(func.count(UserSession.id))).scalar() == 0


def test_session_valid_right_up_to_expiry(session):
    user = make_user(session)
    token = auth.create_session(session, user_id=user.id, now=NOW)
    just_before = NOW + auth.SESSION_LIFETIME - timedelta(seconds=1)
    assert auth.lookup_session(session, token=token, now=just_before) is not None


def test_delete_session_logs_out(session):
    user = make_user(session)
    token = auth.create_session(session, user_id=user.id, now=NOW)
    auth.delete_session(session, token=token)
    assert auth.lookup_session(session, token=token, now=NOW) is None


def test_delete_session_is_idempotent(session):
    auth.delete_session(session, token="never-existed")
    auth.delete_session(session, token="never-existed")


def test_delete_all_sessions_revokes_every_one(session):
    user = make_user(session)
    other = make_user(session, email="b@example.test")
    tokens = [auth.create_session(session, user_id=user.id, now=NOW) for _ in range(3)]
    kept = auth.create_session(session, user_id=other.id, now=NOW)

    assert auth.delete_all_sessions(session, user_id=user.id) == 3
    for t in tokens:
        assert auth.lookup_session(session, token=t, now=NOW) is None
    assert auth.lookup_session(session, token=kept, now=NOW) is not None


# --- invites -----------------------------------------------------------------

def test_invite_round_trip(session):
    token = auth.create_invite(
        session, email="new@example.test", display_name="New", is_admin=True, now=NOW
    )
    invite = auth.consume_invite(session, token=token, now=NOW)
    assert invite is not None
    assert invite.email == "new@example.test"
    assert invite.display_name == "New"
    assert invite.is_admin is True
    assert invite.consumed_at == NOW


def test_invite_cannot_be_consumed_twice(session):
    token = auth.create_invite(
        session, email="once@example.test", display_name="Once", is_admin=False, now=NOW
    )
    assert auth.consume_invite(session, token=token, now=NOW) is not None
    assert auth.consume_invite(session, token=token, now=NOW) is None


def test_expired_invite_is_rejected(session):
    token = auth.create_invite(
        session, email="old@example.test", display_name="Old", is_admin=False, now=NOW
    )
    later = NOW + auth.INVITE_LIFETIME + timedelta(seconds=1)
    assert auth.consume_invite(session, token=token, now=later) is None


def test_unknown_invite_token_is_rejected(session):
    assert auth.consume_invite(session, token="nope", now=NOW) is None


def test_invite_raw_token_is_not_stored(session):
    from sqlalchemy import select

    token = auth.create_invite(
        session, email="h@example.test", display_name="H", is_admin=False, now=NOW
    )
    assert token not in session.execute(select(Invite.token_hash)).scalars().all()
