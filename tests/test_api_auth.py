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
