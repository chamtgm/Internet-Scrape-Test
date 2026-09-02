from datetime import UTC, datetime

from fastapi.testclient import TestClient

from reachstore.api.app import create_app
from reachstore.api.deps import get_session
from reachstore.models import Source

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def make_client(session):
    """A TestClient whose session is the test's rolled-back fixture session.

    dependency_overrides is how the app gets a session it did not open. Without
    it every test would hit the real database_url from .env.
    """
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


def test_sources_endpoint_returns_every_source(session):
    session.add(
        Source(kind="rss", identifier="https://a/feed", tier=1, config_json={}, created_at=NOW)
    )
    session.flush()

    body = make_client(session).get("/api/sources").json()
    assert [s["identifier"] for s in body["sources"]] == ["https://a/feed"]
    assert body["sources"][0]["kind"] == "rss"
    assert body["sources"][0]["item_count"] == 0
    assert body["sources"][0]["last_status"] is None
    assert body["sources"][0]["error_text"] is None


def test_sources_endpoint_is_empty_when_no_sources(session):
    assert make_client(session).get("/api/sources").json()["sources"] == []
