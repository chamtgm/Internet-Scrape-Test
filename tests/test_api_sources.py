from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from reachstore.api.app import create_app
from reachstore.api.deps import get_session
from reachstore.api.schemas import SourceStatusOut
from reachstore.models import Source

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)

VALID_SOURCE_STATUS_KWARGS = dict(
    source_id=1,
    kind="rss",
    identifier="https://a/feed",
    last_status=None,
    last_run_at=None,
    consecutive_failures=0,
    needs_attention=False,
    error_text=None,
    item_count=0,
)


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


def test_source_status_out_rejects_unexpected_field():
    """A field added to query.SourceStatus with no schema counterpart must be a hard
    error, not a silent drop -- that is the whole point of SourceStatusOut(**vars(s))."""
    with pytest.raises(ValidationError):
        SourceStatusOut(**VALID_SOURCE_STATUS_KWARGS, extra_field="unexpected")


def test_source_status_out_requires_every_field():
    with pytest.raises(ValidationError):
        SourceStatusOut(source_id=1, kind="rss")
