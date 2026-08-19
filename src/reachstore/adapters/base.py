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
    """One platform's collection logic. This is Plan 3's primary extension point.

    Contract that `collect.py` relies on:

    - Failures raise `AdapterError` and nothing else. `collect_source` treats
      any other exception as a bug to isolate, not an expected failure mode
      -- wrap platform-specific exceptions (HTTP errors, subprocess failures,
      malformed upstream data) as `AdapterError` inside `fetch`.
    - An empty result returns `[]` rather than raising. "Nothing new to
      report" is not a failure.
    - `published_at` on every returned `NormalizedItem` is timezone-aware UTC,
      or `None` if the upstream source has no timestamp for that item. Never
      a naive datetime.
    - `since` is advisory. Adapters may use it to filter or paginate, or
      ignore it entirely; the orchestrator does not depend on it being
      honored, and today's orchestrator always passes `None` (see F1).
    """

    kind: str
    tier: int

    def fetch(self, identifier: str, since: datetime | None) -> list[NormalizedItem]: ...


class HttpxFetcher:
    """Real HTTP fetcher. Never used in tests."""

    def get(self, url: str, *, timeout: int) -> str:
        try:
            response = httpx.get(url, timeout=timeout, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AdapterError(f"HTTP request failed for {url}: {exc}") from exc
        return response.text


class SubprocessRunner:
    """Real command runner for upstream CLIs installed by agent-reach. Never used in tests."""

    def run(self, args: list[str], *, timeout: int) -> str:
        command = " ".join(args)
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise AdapterError(f"{command} timed out after {timeout}s") from exc
        except FileNotFoundError as exc:
            # Must be caught before OSError, of which it is a subclass, to give
            # a message specific to the missing-binary case.
            raise AdapterError(f"{command} failed: command not found") from exc
        except OSError as exc:
            raise AdapterError(f"{command} failed: {exc}") from exc
        if result.returncode != 0:
            raise AdapterError(f"{args[0]} failed ({result.returncode}): {result.stderr.strip()}")
        return result.stdout
