import httpx
import pytest

from reachstore.adapters.base import AdapterError, HttpxFetcher


def test_httpx_fetcher_wraps_http_status_error(monkeypatch):
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(404, request=request)

    def raise_status_error(*args, **kwargs):
        raise httpx.HTTPStatusError("404 Not Found", request=request, response=response)

    monkeypatch.setattr(httpx, "get", raise_status_error)

    with pytest.raises(AdapterError) as exc_info:
        HttpxFetcher().get("https://example.com", timeout=5)

    assert isinstance(exc_info.value.__cause__, httpx.HTTPStatusError)


def test_httpx_fetcher_wraps_transport_error(monkeypatch):
    def raise_connect_error(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", raise_connect_error)

    with pytest.raises(AdapterError):
        HttpxFetcher().get("https://example.com", timeout=5)
