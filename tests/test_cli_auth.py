"""CLI commands are invoked through Typer's runner rather than as functions, so
argument parsing and exit codes are covered too.

Each command builds its own session via cli._session(), which points at
DATABASE_URL. Monkeypatching _session to hand back the test session is what
keeps these tests off the development database.
"""

import pytest
from typer.testing import CliRunner

from reachstore import cli
from reachstore.models import Invite, User, UserSession

runner = CliRunner()


@pytest.fixture
def cli_session(session, monkeypatch):
    """Point every CLI command at the rolled-back test session.

    The commands call session.commit(); under the conftest fixture's
    join_transaction_mode="create_savepoint" that commits a SAVEPOINT, which
    the outer rollback still discards.
    """
    monkeypatch.setattr(cli, "_session", lambda: session)
    # The commands close the session when they finish; a second command in the
    # same test would then fail. Closing a session bound to an external
    # connection is harmless to re-open, but make it a no-op to be explicit.
    monkeypatch.setattr(session, "close", lambda: None)
    return session


def test_invite_prints_a_setup_url(cli_session):
    """The token goes in a URL fragment, not a query string.

    A fragment is never sent to the server, so this single-use credential
    stays out of access logs, proxy logs, and the Referer header. The path
    stays `/` either way -- see Task 9 for why that part matters.
    """
    result = runner.invoke(
        cli.app, ["invite", "new@example.test", "--name", "New Person"]
    )
    assert result.exit_code == 0
    assert "/#setup=" in result.stdout

    from sqlalchemy import select

    invite = cli_session.execute(select(Invite)).scalars().one()
    assert invite.email == "new@example.test"
    assert invite.display_name == "New Person"
    assert invite.is_admin is False


def test_invite_admin_flag_is_recorded(cli_session):
    from sqlalchemy import select

    result = runner.invoke(
        cli.app, ["invite", "boss@example.test", "--name", "Boss", "--admin"]
    )
    assert result.exit_code == 0
    assert cli_session.execute(select(Invite)).scalars().one().is_admin is True


def test_invite_does_not_print_the_raw_token_twice(cli_session):
    """The token appears once, inside the URL. Printing it separately would
    put it in the shell history twice for no benefit."""
    result = runner.invoke(cli.app, ["invite", "x@example.test", "--name", "X"])
    token = result.stdout.split("#setup=")[1].strip()
    assert result.stdout.count(token) == 1


def test_invite_rejects_a_duplicate_email(cli_session):
    from datetime import UTC, datetime

    cli_session.add(
        User(
            email="taken@example.test",
            display_name="Taken",
            created_at=datetime(2026, 9, 18, tzinfo=UTC),
        )
    )
    cli_session.flush()

    result = runner.invoke(cli.app, ["invite", "taken@example.test", "--name", "Dup"])
    assert result.exit_code == 1
    assert "already" in result.stdout.lower()


def test_set_password_lets_the_user_log_in(cli_session):
    from datetime import UTC, datetime

    from reachstore.api.auth import verify_password

    user = User(
        email="reset@example.test",
        display_name="Reset",
        created_at=datetime(2026, 9, 18, tzinfo=UTC),
    )
    cli_session.add(user)
    cli_session.flush()

    result = runner.invoke(
        cli.app,
        ["set-password", "reset@example.test"],
        # Twice: typer's confirmation_prompt re-asks and compares.
        input="brand-new-password\nbrand-new-password\n",
    )
    assert result.exit_code == 0
    assert verify_password("brand-new-password", user.password_hash)


def test_set_password_rejects_a_short_password(cli_session):
    from datetime import UTC, datetime

    user = User(
        email="short@example.test",
        display_name="Short",
        created_at=datetime(2026, 9, 18, tzinfo=UTC),
    )
    cli_session.add(user)
    cli_session.flush()

    result = runner.invoke(
        cli.app, ["set-password", "short@example.test"], input="abc\nabc\n"
    )
    assert result.exit_code == 1
    assert user.password_hash == ""


def test_set_password_on_an_unknown_email_exits_1(cli_session):
    result = runner.invoke(
        cli.app,
        ["set-password", "ghost@example.test"],
        input="a-long-enough-password\na-long-enough-password\n",
    )
    assert result.exit_code == 1


def test_revoke_sessions_deletes_them_and_reports_the_count(cli_session):
    from datetime import UTC, datetime

    from sqlalchemy import func, select

    from reachstore.api.auth import create_session

    user = User(
        email="revoke@example.test",
        display_name="Revoke",
        created_at=datetime(2026, 9, 18, tzinfo=UTC),
    )
    cli_session.add(user)
    cli_session.flush()
    for _ in range(2):
        create_session(cli_session, user_id=user.id, now=datetime.now(UTC))

    result = runner.invoke(cli.app, ["revoke-sessions", "revoke@example.test"])
    assert result.exit_code == 0
    assert "2" in result.stdout
    assert cli_session.execute(select(func.count(UserSession.id))).scalar() == 0
