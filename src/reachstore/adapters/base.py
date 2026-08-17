from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

import httpx


@dataclass(frozen=True)
class NormalizedItem:
    """Platform-agnostic item. Every adapter emits exactly this shape."""

    external_id: str
    url: str
    content_text: str
    title: str | None = None
    author_handle: str | None = None
    published_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class AdapterError(RuntimeError):
    """Raised when an adapter cannot fetch or parse a source."""


@runtime_checkable
class HttpFetcher(Protocol):
    def get(self, url: str, *, timeout: int) -> str: ...


@runtime_checkable
class CommandRunner(Protocol):
    def run(self, args: list[str], *, timeout: int) -> str: ...


@runtime_checkable
class Adapter(Protocol):
    kind: str
    tier: int

    def fetch(self, identifier: str, since: datetime | None) -> list[NormalizedItem]: ...


class HttpxFetcher:
    """Real HTTP fetcher. Never used in tests."""

    def get(self, url: str, *, timeout: int) -> str:
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
        return response.text


class SubprocessRunner:
    """Real command runner for upstream CLIs installed by agent-reach. Never used in tests."""

    def run(self, args: list[str], *, timeout: int) -> str:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            raise AdapterError(f"{args[0]} failed ({result.returncode}): {result.stderr.strip()}")
        return result.stdout
