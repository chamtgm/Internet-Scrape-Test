import subprocess

import httpx
import pytest

from reachstore.adapters.base import AdapterError, HttpxFetcher, SubprocessRunner


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


def test_subprocess_runner_wraps_missing_binary(monkeypatch):
    """F3: subprocess.run raises FileNotFoundError when the binary does not
    exist. Only the non-zero-exit case was wrapped as AdapterError; this and
    TimeoutExpired leaked past every adapter's promised failure contract."""
    with pytest.raises(AdapterError) as exc_info:
        SubprocessRunner().run(["this-binary-certainly-does-not-exist-xyz"], timeout=5)
    assert isinstance(exc_info.value.__cause__, FileNotFoundError)


def test_subprocess_runner_wraps_timeout():
    """F3: subprocess.run raises TimeoutExpired when the command outlives
    `timeout`. Local and offline: /bin/sleep needs no network."""
    with pytest.raises(AdapterError) as exc_info:
        SubprocessRunner().run(["/bin/sleep", "5"], timeout=1)
    assert isinstance(exc_info.value.__cause__, subprocess.TimeoutExpired)
