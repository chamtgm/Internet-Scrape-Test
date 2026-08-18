from datetime import UTC, datetime

import pytest

from reachstore.adapters.base import AdapterError
from reachstore.adapters.github import GithubRepoAdapter


class FakeRunner:
    def __init__(self, output: str):
        self.output = output
        self.calls: list[list[str]] = []

    def run(self, args: list[str], *, timeout: int) -> str:
        self.calls.append(args)
        return self.output


@pytest.fixture
def runner(fixtures_dir):
    return FakeRunner((fixtures_dir / "github_releases.json").read_text())


def test_kind_and_tier(runner):
    adapter = GithubRepoAdapter(runner)
    assert adapter.kind == "github_repo"
    assert adapter.tier == 1


def test_invokes_gh_with_expected_arguments(runner):
    GithubRepoAdapter(runner).fetch("octo/repo", None)
    assert runner.calls == [["gh", "api", "repos/octo/repo/releases", "--paginate"]]


def test_maps_release_fields(runner):
    first = GithubRepoAdapter(runner).fetch("octo/repo", None)[0]
    assert first.external_id == "900001"
    assert first.url == "https://github.com/octo/repo/releases/tag/v2.1.0"
    assert first.title == "v2.1.0 — faster indexing"
    assert first.author_handle == "octocat"
    assert first.published_at == datetime(2026, 8, 11, 8, 0, tzinfo=UTC)
    assert "Rewrote the indexer" in first.content_text


def test_since_filters_older_releases(runner):
    items = GithubRepoAdapter(runner).fetch("octo/repo", datetime(2026, 8, 1, tzinfo=UTC))
    assert [i.title for i in items] == ["v2.1.0 — faster indexing"]


def test_rejects_identifier_without_owner():
    runner = FakeRunner("[]")
    with pytest.raises(AdapterError):
        GithubRepoAdapter(runner).fetch("repo-only", None)
    assert runner.calls == []


def test_rejects_identifier_with_empty_owner():
    runner = FakeRunner("[]")
    with pytest.raises(AdapterError):
        GithubRepoAdapter(runner).fetch("/repo", None)
    assert runner.calls == []


def test_rejects_identifier_with_empty_repo():
    runner = FakeRunner("[]")
    with pytest.raises(AdapterError):
        GithubRepoAdapter(runner).fetch("owner/", None)
    assert runner.calls == []


def test_invalid_json_raises_adapter_error():
    with pytest.raises(AdapterError):
        GithubRepoAdapter(FakeRunner("not json")).fetch("octo/repo", None)


def test_non_list_json_raises_adapter_error():
    runner = FakeRunner('{"message": "Not Found", "status": "404"}')
    with pytest.raises(AdapterError):
        GithubRepoAdapter(runner).fetch("octo/repo", None)
