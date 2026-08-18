import hashlib

import pytest

from reachstore.adapters.base import AdapterError
from reachstore.adapters.registry import build_registry
from reachstore.adapters.web import WebPageAdapter


class FakeHttp:
    def __init__(self, body: str):
        self.body = body
        self.calls: list[str] = []

    def get(self, url: str, *, timeout: int) -> str:
        self.calls.append(url)
        return self.body


class FakeRunner:
    def run(self, args: list[str], *, timeout: int) -> str:
        return "[]"


@pytest.fixture
def http(fixtures_dir):
    return FakeHttp((fixtures_dir / "jina_page.txt").read_text())


def test_fetches_through_jina_reader(http):
    WebPageAdapter(http).fetch("https://example.com/articles/residential-ips", None)
    assert http.calls == ["https://r.jina.ai/https://example.com/articles/residential-ips"]


def test_returns_single_item_with_extracted_title(http):
    items = WebPageAdapter(http).fetch("https://example.com/articles/residential-ips", None)
    assert len(items) == 1
    assert items[0].title == "How residential IPs affect scraping"
    assert items[0].url == "https://example.com/articles/residential-ips"
    assert "consumer ISPs" in items[0].content_text


def test_external_id_is_content_hash(http):
    item = WebPageAdapter(http).fetch("https://example.com/articles/residential-ips", None)[0]
    assert item.external_id == hashlib.sha256(item.content_text.encode()).hexdigest()


def test_unchanged_page_produces_identical_external_id(http):
    a = WebPageAdapter(http).fetch("https://example.com/x", None)[0]
    b = WebPageAdapter(http).fetch("https://example.com/x", None)[0]
    assert a.external_id == b.external_id


def test_empty_body_raises_adapter_error():
    with pytest.raises(AdapterError):
        WebPageAdapter(FakeHttp("   ")).fetch("https://example.com/x", None)


def test_registry_exposes_all_tier1_kinds(http):
    registry = build_registry(http, FakeRunner())
    assert set(registry) == {"rss", "github_repo", "web_page"}
    assert all(adapter.tier == 1 for adapter in registry.values())
