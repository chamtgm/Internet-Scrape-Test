from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from reachstore.config import get_settings
from reachstore.db import make_engine, make_session_factory


@lru_cache
def get_engine() -> Engine:
    """One engine, and therefore one connection pool, for the process.

    `cli.py` builds an engine per invocation, which is correct for a one-shot
    process and fatal for a server: a fresh pool per request would exhaust
    Postgres connections under any sustained use.
    """
    return make_engine(get_settings().database_url)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return make_session_factory(get_engine())


def get_session() -> Iterator[Session]:
    """Request-scoped session. Overridden in tests via dependency_overrides."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def raw_dir() -> Path:
    return get_settings().raw_dir
