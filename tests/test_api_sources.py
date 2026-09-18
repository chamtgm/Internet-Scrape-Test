from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

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


def test_sources_endpoint_returns_every_source(session, admin_client):
    session.add(
        Source(kind="rss", identifier="https://a/feed", tier=1, config_json={}, created_at=NOW)
    )
    session.flush()

    body = admin_client.get("/api/sources").json()
    assert [s["identifier"] for s in body["sources"]] == ["https://a/feed"]
    assert body["sources"][0]["kind"] == "rss"
    assert body["sources"][0]["item_count"] == 0
    assert body["sources"][0]["last_status"] is None
    assert body["sources"][0]["error_text"] is None


def test_sources_endpoint_is_empty_when_no_sources(admin_client):
    assert admin_client.get("/api/sources").json()["sources"] == []


def test_source_status_out_rejects_unexpected_field():
    """A field added to query.SourceStatus with no schema counterpart must be a hard
    error, not a silent drop -- that is the whole point of SourceStatusOut(**vars(s))."""
    with pytest.raises(ValidationError):
        SourceStatusOut(**VALID_SOURCE_STATUS_KWARGS, extra_field="unexpected")


def test_source_status_out_requires_every_field():
    with pytest.raises(ValidationError):
        SourceStatusOut(source_id=1, kind="rss")
