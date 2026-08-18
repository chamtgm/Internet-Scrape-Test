from __future__ import annotations

from reachstore.adapters.base import Adapter, CommandRunner, HttpFetcher
from reachstore.adapters.github import GithubRepoAdapter
from reachstore.adapters.rss import RssAdapter
from reachstore.adapters.web import WebPageAdapter


def build_registry(http: HttpFetcher, runner: CommandRunner) -> dict[str, Adapter]:
    """Map source kind -> adapter instance. Dependencies are injected so tests use fakes."""
    adapters: list[Adapter] = [
        RssAdapter(http),
        GithubRepoAdapter(runner),
        WebPageAdapter(http),
    ]
    return {adapter.kind: adapter for adapter in adapters}
