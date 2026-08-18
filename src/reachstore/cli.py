from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import typer
from sqlalchemy.orm import Session

from reachstore.adapters.base import Adapter, HttpxFetcher, SubprocessRunner
from reachstore.adapters.registry import build_registry
from reachstore.collect import collect_tier
from reachstore.config import get_settings
from reachstore.db import make_engine, make_session_factory
from reachstore.models import Source
from reachstore.query import search as query_search
from reachstore.query import source_health

app = typer.Typer(help="Agent-Reach knowledge store")


def build_default_registry() -> dict[str, Adapter]:
    return build_registry(HttpxFetcher(), SubprocessRunner())


def _session() -> Session:
    settings = get_settings()
    return make_session_factory(make_engine(settings.database_url))()


def _raw_dir() -> Path:
    path = get_settings().raw_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


@app.command("add-source")
def add_source(kind: str, identifier: str, tier: int = 1) -> None:
    """Register a source to collect from."""
    session = _session()
    session.add(
        Source(
            kind=kind,
            identifier=identifier,
            tier=tier,
            config_json={},
            created_at=datetime.now(UTC),
        )
    )
    session.commit()
    typer.echo(f"added {kind} {identifier} (tier {tier})")


@app.command()
def collect(tier: int = 1, force: bool = False) -> None:
    """Collect every source in a tier."""
    session = _session()
    results = collect_tier(
        session,
        tier=tier,
        registry=build_default_registry(),
        raw_dir=_raw_dir(),
        now=datetime.now(UTC),
        force=force,
    )
    session.commit()
    for result in results:
        if result.status == "success":
            typer.echo(f"source {result.source_id}: {result.items_new} new / {result.items_found} found")
        else:
            typer.echo(f"source {result.source_id}: failed — {result.error_text}")
    typer.echo(f"{len(results)} source(s) processed")


@app.command()
def search(
    q: str,
    user_id: int = typer.Option(..., "--user-id"),
    kind: str | None = None,
    limit: int = 20,
) -> None:
    """Search collected items."""
    session = _session()
    items = query_search(
        session, user_id=user_id, q=q, kinds=[kind] if kind else None, limit=limit
    )
    for item in items:
        typer.echo(f"{item.published_at or '-'}  {item.title}\n    {item.url}")
    typer.echo(f"{len(items)} result(s)")


@app.command()
def health(user_id: int = typer.Option(..., "--user-id")) -> None:
    """Show per-source collection health."""
    session = _session()
    for status in source_health(session, user_id=user_id):
        flag = "NEEDS ATTENTION" if status.needs_attention else status.last_status or "never run"
        typer.echo(f"[{flag}] {status.kind} {status.identifier} (failures: {status.consecutive_failures})")


if __name__ == "__main__":
    app()
