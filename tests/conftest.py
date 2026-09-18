import itertools
import os
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from reachstore.config import get_settings
from reachstore.db import make_engine, make_session_factory


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = get_settings().test_database_url
    if not url:
        pytest.fail("TEST_DATABASE_URL is not set; copy .env.example to .env")
    return url


def _guard_test_database(test_url: str, primary_url: str) -> None:
    """Refuse to proceed if the test database might be a real one.

    The `engine` fixture below runs `DROP SCHEMA public CASCADE` against
    whatever this URL resolves to. A single copy-paste mistake in `.env`, or a
    CI environment that defines only one database URL, would otherwise
    destroy production data with no warning. Two independent, cheap checks:
    the test URL must differ from the primary URL, and the database name must
    end in `_test`.
    """
    if test_url == primary_url:
        pytest.fail(
            "TEST_DATABASE_URL is identical to DATABASE_URL; refusing to run "
            "`DROP SCHEMA public CASCADE` against what may be the primary database."
        )
    db_name = test_url.rsplit("/", 1)[-1].split("?", 1)[0]
    if not db_name.endswith("_test"):
        pytest.fail(
            f"TEST_DATABASE_URL database {db_name!r} does not end in '_test'; "
            "refusing to run `DROP SCHEMA public CASCADE` against it."
        )


@pytest.fixture(scope="session")
def engine(test_database_url: str) -> Generator[Engine, None, None]:
    _guard_test_database(test_database_url, get_settings().database_url)
    eng = make_engine(test_database_url)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    os.environ["ALEMBIC_DATABASE_URL"] = test_database_url
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Generator[Session, None, None]:
    """Each test runs inside a transaction that is rolled back afterwards."""
    connection = engine.connect()
    transaction = connection.begin()
    factory = make_session_factory(engine)
    # join_transaction_mode="create_savepoint" makes session.commit() commit a SAVEPOINT
    # instead of the outer transaction, so code under test can commit freely and the
    # fixture's rollback still discards everything.
    sess = factory(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield sess
    finally:
        sess.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def raw_dir(tmp_path: Path) -> Path:
    d = tmp_path / "raw"
    d.mkdir()
    return d


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _reset_collect_flag():
    """`collect_runner._running` is a module global; a test that leaves it set
    would poison every later test in the same process."""
    from reachstore.api import collect_runner

    collect_runner._running = False
    yield
    collect_runner._running = False


@pytest.fixture
def make_user(session):
    """Create a user with a usable password. Returns (user, password)."""
    from reachstore.api.auth import hash_password
    from reachstore.models import User

    counter = itertools.count(1)

    def _make(*, is_admin=False, email=None, password="test-password-1234"):
        n = next(counter)
        user = User(
            email=email or f"user{n}@example.test",
            display_name=f"User {n}",
            password_hash=hash_password(password),
            is_admin=is_admin,
            created_at=datetime(2026, 9, 18, tzinfo=UTC),
        )
        session.add(user)
        session.flush()
        return user, password

    return _make


@pytest.fixture
def client_for(session, make_user):
    """A TestClient carrying a real session cookie. Returns (client, user, password)."""
    from fastapi.testclient import TestClient

    from reachstore.api.app import create_app
    from reachstore.api.auth import COOKIE_NAME, create_session
    from reachstore.api.deps import get_session

    def _client(*, is_admin=False, email=None):
        user, password = make_user(is_admin=is_admin, email=email)
        # Real clock, not a fixed date: get_current_user checks expiry against
        # datetime.now(UTC), so a session stamped with a literal date would be
        # expired by the time anyone runs this suite later.
        token = create_session(session, user_id=user.id, now=datetime.now(UTC))
        app = create_app()
        app.dependency_overrides[get_session] = lambda: session
        client = TestClient(app)
        client.cookies.set(COOKIE_NAME, token)
        return client, user, password

    return _client


@pytest.fixture
def admin_client(client_for):
    client, _user, _pw = client_for(is_admin=True)
    return client


@pytest.fixture
def user_client(client_for):
    client, _user, _pw = client_for(is_admin=False)
    return client


@pytest.fixture
def anon_client(session):
    """A TestClient with no session cookie."""
    from fastapi.testclient import TestClient

    from reachstore.api.app import create_app
    from reachstore.api.deps import get_session

    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)
