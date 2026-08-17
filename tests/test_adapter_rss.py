from datetime import UTC, datetime

import pytest

from reachstore.adapters.base import AdapterError
from reachstore.adapters.rss import RssAdapter


class FakeHttp:
    def __init__(self, body: str):
        self.body = body
        self.calls: list[str] = []

    def get(self, url: str, *, timeout: int) -> str:
        self.calls.append(url)
        return self.body


@pytest.fixture
def adapter(fixtures_dir):
    return RssAdapter(FakeHttp((fixtures_dir / "rss_sample.xml").read_text()))


def test_kind_and_tier(adapter):
    assert adapter.kind == "rss"
    assert adapter.tier == 1


def test_parses_all_entries(adapter):
    items = adapter.fetch("https://example.com/feed", None)
    assert len(items) == 2


def test_maps_fields_correctly(adapter):
    first = adapter.fetch("https://example.com/feed", None)[0]
    assert first.external_id == "https://example.com/posts/tsvector"
    assert first.url == "https://example.com/posts/tsvector"
    assert first.title == "Understanding tsvector"
    assert first.author_handle == "editor@example.com (Sam Rivers)"
    assert first.published_at == datetime(2026, 8, 12, 9, 30, tzinfo=UTC)
    assert "full-text search" in first.content_text
    assert first.raw["link"] == "https://example.com/posts/tsvector"


def test_since_filters_older_entries(adapter):
    items = adapter.fetch("https://example.com/feed", datetime(2026, 8, 10, tzinfo=UTC))
    assert [i.title for i in items] == ["Understanding tsvector"]


def test_missing_author_is_none(adapter):
    second = adapter.fetch("https://example.com/feed", None)[1]
    assert second.author_handle is None


def test_unparseable_body_raises_adapter_error():
    adapter = RssAdapter(FakeHttp("this is not a feed at all"))
    with pytest.raises(AdapterError):
        adapter.fetch("https://example.com/feed", None)


def test_non_utc_offset_is_converted_to_utc(fixtures_dir):
    adapter = RssAdapter(FakeHttp((fixtures_dir / "rss_edge_cases.xml").read_text()))
    items = adapter.fetch("https://example.com/feed", None)
    dated = next(i for i in items if i.title == "Dated with offset")
    assert dated.published_at == datetime(2026, 8, 12, 1, 30, tzinfo=UTC)


def test_undated_entry_survives_since_filter(fixtures_dir):
    adapter = RssAdapter(FakeHttp((fixtures_dir / "rss_edge_cases.xml").read_text()))
    items = adapter.fetch("https://example.com/feed", datetime(2026, 8, 13, tzinfo=UTC))
    assert [i.title for i in items] == ["Undated post"]


def test_empty_but_valid_feed_returns_no_items(fixtures_dir):
    adapter = RssAdapter(FakeHttp((fixtures_dir / "rss_empty.xml").read_text()))
    items = adapter.fetch("https://example.com/feed", None)
    assert items == []
