from datetime import UTC, datetime

from typer.testing import CliRunner

from reachstore import cli
from reachstore.adapters.base import NormalizedItem
from reachstore.models import Item, Source, User
from sqlalchemy import select

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
runner = CliRunner()


class StubAdapter:
    kind = "rss"
    tier = 1

    def fetch(self, identifier: str, since):
        return [NormalizedItem(external_id="1", url="https://a/1", title="hello tsvector", content_text="body text")]


def test_add_source_then_collect_then_search(session, raw_dir, monkeypatch):
    user = User(email="u@example.com", display_name="u", created_at=NOW)
    session.add(user)
    session.flush()

    monkeypatch.setattr(cli, "_session", lambda: session)
    monkeypatch.setattr(cli, "_raw_dir", lambda: raw_dir)
    monkeypatch.setattr(cli, "build_default_registry", lambda: {"rss": StubAdapter()})

    result = runner.invoke(cli.app, ["add-source", "rss", "https://a/feed", "--tier", "1"])
    assert result.exit_code == 0
    assert session.execute(select(Source)).scalars().one().identifier == "https://a/feed"

    result = runner.invoke(cli.app, ["collect", "--tier", "1"])
    assert result.exit_code == 0
    assert "1 new" in result.stdout
    assert session.execute(select(Item)).scalars().one().title == "hello tsvector"

    result = runner.invoke(cli.app, ["search", "tsvector", "--user-id", str(user.id)])
    assert result.exit_code == 0
    assert "hello tsvector" in result.stdout


def test_collect_reports_failures_without_crashing(session, raw_dir, monkeypatch):
    class BrokenAdapter(StubAdapter):
        def fetch(self, identifier: str, since):
            raise RuntimeError("upstream exploded")

    session.add(Source(kind="rss", identifier="https://a/feed", tier=1, config_json={}, created_at=NOW))
    session.flush()

    monkeypatch.setattr(cli, "_session", lambda: session)
    monkeypatch.setattr(cli, "_raw_dir", lambda: raw_dir)
    monkeypatch.setattr(cli, "build_default_registry", lambda: {"rss": BrokenAdapter()})

    result = runner.invoke(cli.app, ["collect", "--tier", "1"])
    assert result.exit_code == 1
    assert "failed" in result.stdout
    assert "upstream exploded" in result.stdout


def test_collect_exits_zero_when_some_sources_succeed(session, raw_dir, monkeypatch):
    class BrokenAdapter:
        kind = "atom"
        tier = 1

        def fetch(self, identifier: str, since):
            raise RuntimeError("upstream exploded")

    session.add(Source(kind="rss", identifier="https://a/feed", tier=1, config_json={}, created_at=NOW))
    session.add(Source(kind="atom", identifier="https://b/feed", tier=1, config_json={}, created_at=NOW))
    session.flush()

    monkeypatch.setattr(cli, "_session", lambda: session)
    monkeypatch.setattr(cli, "_raw_dir", lambda: raw_dir)
    monkeypatch.setattr(
        cli, "build_default_registry", lambda: {"rss": StubAdapter(), "atom": BrokenAdapter()}
    )

    result = runner.invoke(cli.app, ["collect", "--tier", "1"])
    assert result.exit_code == 0
    assert "failed" in result.stdout
    assert "1 new" in result.stdout


def test_health_lists_source_status(session, raw_dir, monkeypatch):
    """F4: health is a global operator view with no per-user scoping -- the
    old --user-id option looked like tenant isolation but was ignored by
    source_health, so it was removed rather than left misleading."""
    session.add(Source(kind="rss", identifier="https://a/feed", tier=1, config_json={}, created_at=NOW))
    session.flush()

    monkeypatch.setattr(cli, "_session", lambda: session)

    result = runner.invoke(cli.app, ["health"])
    assert result.exit_code == 0
    assert "https://a/feed" in result.stdout
