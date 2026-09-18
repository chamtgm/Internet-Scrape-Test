"""One table, three clients. A new endpoint added without a row here is the
failure this file exists to catch."""

import re

import pytest

# (method, path, anonymous, non-admin, admin)
CASES = [
    ("GET", "/api/feed", 401, 200, 200),
    ("GET", "/api/search?q=anything", 401, 200, 200),
    ("GET", "/api/items/999999", 401, 404, 404),
    ("GET", "/api/sources", 401, 403, 200),
    ("GET", "/api/auth/me", 401, 200, 200),
    ("POST", "/api/auth/logout", 401, 200, 200),
    ("GET", "/api/catalog", 401, 200, 200),
    ("DELETE", "/api/subscriptions/999999", 401, 204, 204),
]


def test_every_api_route_is_in_the_matrix():
    """Makes this file's opening claim true rather than aspirational.

    Without this, a new endpoint added with no CASES row leaves the suite
    green and its access level unasserted -- which is precisely how an
    endpoint ships unauthenticated.
    """
    # Walk `router.routes` directly rather than `create_app().routes`: on the
    # installed fastapi==0.141.1 / starlette==1.6.0, FastAPI.include_router()
    # wraps the sub-router in an opaque `_IncludedRouter` node with no `.path`,
    # so `create_app().routes` no longer flattens our endpoints into it --
    # every route from `router` would silently read as "not /api", and this
    # test would pass with zero real coverage (verified: removing a CASES row
    # for a real endpoint did not fail this test against `create_app().routes`).
    # `router` is the actual source of truth for what this app serves under
    # /api, and reading it directly is immune to how FastAPI happens to wire
    # included routers internally.
    from reachstore.api.routes import router

    # Exempt by design, each for a stated reason:
    #   /api/auth/login  - must be reachable anonymously; that IS its contract
    #   /api/auth/setup  - same, and it is covered by tests/test_api_auth.py
    #   /api/collect     - covered by test_collect_is_admin_only, which needs
    #                      a stubbed runner the table-driven test cannot supply
    EXEMPT = {
        "/api/auth/login",
        "/api/auth/setup",
        "/api/collect",
    }
    covered = {path.split("?")[0] for _method, path, *_ in CASES}
    # A route's `.path` is a template ("/api/items/{item_id}"), but CASES
    # holds concrete resolved paths ("/api/items/999999") -- plain string
    # equality never matches the two, which would leave every templated
    # route (pre-existing /api/items/{item_id} included) reading as
    # "missing" even with a matrix row. Match a covered path against a
    # template by turning "{param}" segments into a wildcard.
    def _covered(template: str) -> bool:
        pattern = "^" + re.sub(r"\{[^/]+\}", r"[^/]+", template) + "$"
        return any(re.match(pattern, c) for c in covered)

    missing = []
    for route in router.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api") or path in EXEMPT or _covered(path):
            continue
        missing.append(path)
    assert not missing, f"endpoints with no permission-matrix row: {sorted(set(missing))}"


@pytest.fixture
def no_op_collect(monkeypatch):
    """POST /api/collect returns 202 and schedules real work. The matrix cares
    only about the status code, so the background task is stubbed out -- the
    suite must make no network calls."""
    from reachstore.api import collect_runner

    monkeypatch.setattr(
        collect_runner,
        "run_collection",
        lambda tier, force: setattr(collect_runner, "_running", False),
    )


@pytest.mark.parametrize(("method", "path", "anon", "user", "admin"), CASES)
def test_permission_matrix(method, path, anon, user, admin, anon_client, user_client, admin_client):
    for label, client, expected in (
        ("anon", anon_client, anon),
        ("user", user_client, user),
        ("admin", admin_client, admin),
    ):
        response = client.request(method, path)
        assert response.status_code == expected, (
            f"{method} {path} as {label}: expected {expected}, got {response.status_code}"
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
