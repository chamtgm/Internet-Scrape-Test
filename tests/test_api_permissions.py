"""One table, three clients. A new endpoint added without a row here is the
failure this file exists to catch."""

import pytest

# (method, path, anonymous, non-admin, admin)
CASES = [
    ("GET", "/api/feed", 401, 200, 200),
    ("GET", "/api/search?q=anything", 401, 200, 200),
    ("GET", "/api/items/999999", 401, 404, 404),
    ("GET", "/api/sources", 401, 403, 200),
    ("GET", "/api/auth/me", 401, 200, 200),
    ("POST", "/api/auth/logout", 401, 200, 200),
]


@pytest.fixture
def no_op_collect(monkeypatch):
    """POST /api/collect returns 202 and schedules real work. The matrix cares
    only about the status code, so the background task is stubbed out -- the
    suite must make no network calls."""
    from reachstore.api import collect_runner

    monkeypatch.setattr(collect_runner, "run_collection", lambda tier, force: None)


@pytest.mark.parametrize(("method", "path", "anon", "user", "admin"), CASES)
def test_permission_matrix(method, path, anon, user, admin, anon_client, user_client, admin_client):
    for client, expected in ((anon_client, anon), (user_client, user), (admin_client, admin)):
        response = client.request(method, path)
        assert response.status_code == expected, (
            f"{method} {path} as {client}: expected {expected}, got {response.status_code}"
        )


def test_collect_is_admin_only(anon_client, user_client, admin_client, no_op_collect):
    body = {"tier": 1}
    assert anon_client.post("/api/collect", json=body).status_code == 401
    assert user_client.post("/api/collect", json=body).status_code == 403
    assert admin_client.post("/api/collect", json=body).status_code == 202


def test_an_unknown_cookie_is_401_not_500(session):
    """A cookie left over from a revoked or deleted session must read as
    'not logged in', not as a crash."""
    from fastapi.testclient import TestClient

    from reachstore.api.app import create_app
    from reachstore.api.auth import COOKIE_NAME
    from reachstore.api.deps import get_session

    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)
    client.cookies.set(COOKIE_NAME, "this-token-was-never-issued")

    assert client.get("/api/feed").status_code == 401


def test_default_user_id_is_gone():
    """The constant existed only to keep the tenant path live before there were
    users. A surviving import would mean a route is still hard-coded to user 1."""
    from reachstore.api import deps

    assert not hasattr(deps, "DEFAULT_USER_ID")
