import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

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
def engine(test_database_url: str):
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
def session(engine):
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
