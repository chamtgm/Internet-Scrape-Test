from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import typer
from sqlalchemy.orm import Session

from reachstore.adapters.base import Adapter, HttpxFetcher, SubprocessRunner
from reachstore.adapters.registry import build_registry
from reachstore.api.auth import (
    MIN_PASSWORD_LENGTH,
    create_invite,
    delete_all_sessions,
    find_user_by_email,
    hash_password,
    normalize_email,
)
from reachstore.collect import collect_tier
from reachstore.config import get_settings
from reachstore.db import make_engine, make_session_factory
from reachstore.models import Source
from reachstore.query import get_source
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
    """Register a source to collect from.

    Validates `kind` against the adapter registry and is idempotent: adding
    the same (kind, identifier) again succeeds with a message rather than
    raising the bare IntegrityError on uq_sources_kind_identifier that an
    unguarded insert would produce. An unknown kind (e.g. a typo like "rrs"
    for "rss") is rejected here rather than silently creating a source that
    collect_tier would skip forever with no adapter, no fetch_run, and no
    error -- the only symptom being a "never run" line in `health`.
    """
    valid_kinds = sorted(build_default_registry().keys())
    if kind not in valid_kinds:
        typer.echo(f"unknown kind {kind!r}; valid kinds: {', '.join(valid_kinds)}")
        raise typer.Exit(code=1)

    session = _session()
    if get_source(session, kind=kind, identifier=identifier) is not None:
        typer.echo(f"already registered: {kind} {identifier}")
        return

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
    """Collect every source in a tier.

    Exit code: 0 if the tier was empty or at least one source succeeded
    (a single failing source is expected and tolerated by the circuit
    breaker); 1 if the tier had at least one source and every one of them
    failed, which usually means something systemic is wrong (database
    unreachable, network down, credentials expired) and a human should look.
    """
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
    if results and all(result.status == "failed" for result in results):
        raise typer.Exit(code=1)


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
def health() -> None:
    """Show per-source collection health. A global operator view: sources
    have no owner, so this is not scoped to any user."""
    session = _session()
    for status in source_health(session):
        flag = "NEEDS ATTENTION" if status.needs_attention else status.last_status or "never run"
        typer.echo(f"[{flag}] {status.kind} {status.identifier} (failures: {status.consecutive_failures})")


@app.command()
def invite(
    email: str,
    name: str = typer.Option(..., "--name", help="Display name for the new account."),
    admin: bool = typer.Option(False, "--admin", help="Grant operator access."),
) -> None:
    """Issue a one-time setup link for a new account.

    There is no signup endpoint: an account begins with someone who already
    has shell access to this machine. That is the entire access-control story
    for a localhost tool.
    """
    # Normalise once, up front, so every echo below reports the address as it
    # is actually stored. Echoing the operator's casing would leave them
    # believing an address exists in a form the database does not hold.
    email = normalize_email(email)
    session = _session()
    try:
        existing = find_user_by_email(session, email)
        if existing is not None:
            typer.echo(f"{email} already has an account (id {existing.id}).")
            raise typer.Exit(code=1)

        token = create_invite(
            session,
            email=email,
            display_name=name,
            is_admin=admin,
            now=datetime.now(UTC),
        )
        session.commit()
    finally:
        session.close()

    # A URL fragment, not a query string: `#setup=<token>` is never sent to
    # the server, so this single-use credential stays out of access logs,
    # proxy logs, and the Referer header. The path stays `/`, which both the
    # Vite dev server and FastAPI's StaticFiles mount already serve.
    base = get_settings().web_base_url.rstrip("/")
    typer.echo(f"Invite for {email} ({'admin' if admin else 'user'}), valid 7 days.")
    typer.echo(f"{base}/#setup={token}")
    typer.echo("The link works once. Re-run this command to issue another.")


@app.command("set-password")
def set_password(email: str) -> None:
    """Set an existing account's password, prompting without echo."""
    # confirmation_prompt asks twice and compares, so a typo cannot silently
    # become the new password -- there is no email reset to recover with.
    password = typer.prompt("New password", hide_input=True, confirmation_prompt=True)
    if len(password) < MIN_PASSWORD_LENGTH:
        typer.echo(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        raise typer.Exit(code=1)

    session = _session()
    try:
        user = find_user_by_email(session, email)
        if user is None:
            typer.echo(f"No account for {email}.")
            raise typer.Exit(code=1)
        user.password_hash = hash_password(password)
        session.commit()
        typer.echo(f"Password set for {email}.")
    finally:
        session.close()


@app.command("revoke-sessions")
def revoke_sessions(email: str) -> None:
    """Log an account out of every browser.

    Sessions are rows, not signed tokens, so revocation is a DELETE that takes
    effect on the next request. A stateless signed cookie could not be
    withdrawn before it expired.
    """
    session = _session()
    try:
        user = find_user_by_email(session, email)
        if user is None:
            typer.echo(f"No account for {email}.")
            raise typer.Exit(code=1)
        count = delete_all_sessions(session, user_id=user.id)
        session.commit()
        typer.echo(f"Revoked {count} session(s) for {email}.")
    finally:
        session.close()


if __name__ == "__main__":
    app()
