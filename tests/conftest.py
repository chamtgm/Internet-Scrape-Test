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


@pytest.fixture(scope="session")
def engine(test_database_url: str):
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
