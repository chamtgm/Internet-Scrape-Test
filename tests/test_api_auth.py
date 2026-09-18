from datetime import UTC, datetime, timedelta

from reachstore.api import auth
from reachstore.api.auth import COOKIE_NAME


def test_login_sets_a_cookie_and_returns_the_user(anon_client, make_user):
    user, password = make_user(email="alice@example.test")

    response = anon_client.post(
        "/api/auth/login", json={"email": "alice@example.test", "password": password}
    )
    assert response.status_code == 200
    assert response.json()["email"] == "alice@example.test"
    assert response.json()["is_admin"] is False
    assert COOKIE_NAME in response.cookies


def test_login_then_me_returns_the_same_user(anon_client, make_user):
    _user, password = make_user(email="bob@example.test")
    anon_client.post(
        "/api/auth/login", json={"email": "bob@example.test", "password": password}
    )
    me = anon_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "bob@example.test"


def test_me_without_a_session_is_401(anon_client):
    assert anon_client.get("/api/auth/me").status_code == 401


def test_wrong_password_and_unknown_email_are_indistinguishable(anon_client, make_user):
    """Identical status and body for both, so the response cannot be used to
    discover which addresses have accounts."""
    make_user(email="real@example.test", password="the-real-password")

    wrong = anon_client.post(
        "/api/auth/login", json={"email": "real@example.test", "password": "nope"}
    )
    unknown = anon_client.post(
        "/api/auth/login", json={"email": "ghost@example.test", "password": "nope"}
    )

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_login_rejects_the_empty_password_hash(anon_client, session):
    """The pre-existing hand-verify row has password_hash == "". It must not be
    loggable-in with an empty password, or with anything else."""
    from datetime import UTC, datetime

    from reachstore.models import User

    session.add(
        User(
            email="legacy@example.test",
            display_name="Legacy",
            password_hash="",
            created_at=datetime(2026, 9, 18, tzinfo=UTC),
        )
    )
    session.flush()

    for attempt in ("", "anything"):
        response = anon_client.post(
            "/api/auth/login", json={"email": "legacy@example.test", "password": attempt}
        )
        assert response.status_code == 401


def test_logout_invalidates_the_session(client_for):
    client, _user, _pw = client_for()
    assert client.get("/api/auth/me").status_code == 200

    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_logout_without_a_session_is_401(anon_client):
    assert anon_client.post("/api/auth/logout").status_code == 401


def test_admin_flag_is_reported(client_for):
    client, _user, _pw = client_for(is_admin=True)
    assert client.get("/api/auth/me").json()["is_admin"] is True


# --- setup -------------------------------------------------------------------


def _invite(session, *, email="invited@example.test", is_admin=False):
    return auth.create_invite(
        session,
        email=email,
        display_name="Invited",
        is_admin=is_admin,
        now=datetime.now(UTC),
    )


def test_setup_creates_the_account_and_logs_it_in(anon_client, session):
    token = _invite(session)

    response = anon_client.post(
        "/api/auth/setup", json={"token": token, "password": "a-good-password"}
    )
    assert response.status_code == 200
    assert response.json()["email"] == "invited@example.test"
    assert response.json()["display_name"] == "Invited"
    assert COOKIE_NAME in response.cookies

    # Already logged in -- no second trip through login.
    assert anon_client.get("/api/auth/me").status_code == 200


def test_setup_carries_the_invited_admin_flag(anon_client, session):
    token = _invite(session, email="newboss@example.test", is_admin=True)
    body = anon_client.post(
        "/api/auth/setup", json={"token": token, "password": "a-good-password"}
    ).json()
    assert body["is_admin"] is True


def test_the_new_account_can_log_in_afterwards(anon_client, session):
    token = _invite(session, email="later@example.test")
    anon_client.post(
        "/api/auth/setup", json={"token": token, "password": "a-good-password"}
    )
    anon_client.post("/api/auth/logout")

    response = anon_client.post(
        "/api/auth/login",
        json={"email": "later@example.test", "password": "a-good-password"},
    )
    assert response.status_code == 200


def test_setup_token_works_exactly_once(anon_client, session):
    token = _invite(session, email="once@example.test")
    assert (
        anon_client.post(
            "/api/auth/setup", json={"token": token, "password": "a-good-password"}
        ).status_code
        == 200
    )
    second = anon_client.post(
        "/api/auth/setup", json={"token": token, "password": "another-password"}
    )
    assert second.status_code == 400


def test_setup_rejects_an_unknown_token(anon_client):
    response = anon_client.post(
        "/api/auth/setup", json={"token": "never-issued", "password": "a-good-password"}
    )
    assert response.status_code == 400


def test_setup_rejects_an_expired_invite(anon_client, session):
    """Stamped far enough in the past that the handler's real clock is past
    expiry, since the handler reads datetime.now(UTC) and cannot be injected."""
    long_ago = datetime.now(UTC) - auth.INVITE_LIFETIME - timedelta(days=1)
    token = auth.create_invite(
        session,
        email="stale@example.test",
        display_name="Stale",
        is_admin=False,
        now=long_ago,
    )
    response = anon_client.post(
        "/api/auth/setup", json={"token": token, "password": "a-good-password"}
    )
    assert response.status_code == 400


def test_setup_rejects_a_short_password_without_consuming_the_invite(anon_client, session):
    """Validation must come before consumption, or a typo burns the link and
    the person has to ask the operator for a new one."""
    token = _invite(session, email="typo@example.test")

    assert (
        anon_client.post("/api/auth/setup", json={"token": token, "password": "abc"}).status_code
        == 400
    )
    assert (
        anon_client.post(
            "/api/auth/setup", json={"token": token, "password": "a-good-password"}
        ).status_code
        == 200
    )


def test_setup_is_409_when_the_email_already_has_an_account(anon_client, session, make_user):
    """An invite issued before the account existed must not be able to take it
    over. 409 rather than the uniform 400, per the spec: the holder of the
    token already knows the email it names, so saying "that account exists"
    leaks nothing they did not supply, and it is the one failure a person can
    actually act on.
    """
    make_user(email="collide@example.test")
    token = _invite(session, email="collide@example.test")

    response = anon_client.post(
        "/api/auth/setup", json={"token": token, "password": "a-good-password"}
    )
    assert response.status_code == 409
