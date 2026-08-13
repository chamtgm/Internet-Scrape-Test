# Core Store + Tier-1 Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the storage spine and Tier-1 collection for the Agent-Reach Knowledge Store — a Postgres-backed store that collects GitHub, RSS, and web-page sources, stores them raw, and searches them with tenant isolation.

**Architecture:** A Python package (`reachstore`) with four layers, bottom-up: SQLAlchemy models + Alembic migrations, a store layer with idempotent upserts, a query layer that owns every SQL statement and the tenant-isolation filter, and adapters that convert upstream-tool output into a single `NormalizedItem` shape. A collection orchestrator ties adapters to the store with per-source failure isolation. External dependencies (HTTP, subprocess) are injected so the entire test suite runs offline.

**Tech Stack:** Python 3.11+, PostgreSQL 16, SQLAlchemy 2.x, Alembic, psycopg 3, pytest, Typer, feedparser, httpx. Postgres runs locally via Docker Compose.

## Global Constraints

- Python 3.11 or newer. Type hints on all public functions.
- PostgreSQL 16. No SQLite fallback — the schema uses Postgres-specific `tsvector` and `JSONB`.
- **No network access in tests.** Every external call goes through an injected dependency; tests supply fakes backed by committed fixture files.
- **No wall-clock reads inside logic.** Functions that need the current time take a `now: datetime` parameter. Only the CLI reads the real clock.
- All SQL lives in `store.py` and `query.py`. No other module may import `sqlalchemy.select` or write raw SQL.
- Tenant isolation predicate: an item is visible to a user when `items.owner_user_id IS NULL OR items.owner_user_id = :user_id`. This appears in exactly one function.
- Every collection operation must be idempotent — safe to run any number of times.
- Free tooling only. No paid services, no API keys required for Tier-1.
- Timestamps are timezone-aware UTC (`TIMESTAMPTZ`).

## File Structure

```
pyproject.toml                       Package metadata, dependencies, pytest config
docker-compose.dev.yml               Local Postgres 16
.env.example                         Documented environment variables
alembic.ini                          Alembic configuration
migrations/env.py                    Alembic runtime wiring
migrations/versions/0001_initial.py  Full 7-table schema + tsvector + GIN index

src/reachstore/config.py             Settings loaded from environment
src/reachstore/db.py                 Engine and session factory
src/reachstore/models.py             SQLAlchemy ORM models (7 tables)
src/reachstore/store.py              upsert_items() — the only writer of items
src/reachstore/query.py              search / feed / get_item / source_health
src/reachstore/collect.py            Orchestration, failure isolation, backoff
src/reachstore/cli.py                Typer CLI entrypoints

src/reachstore/adapters/base.py      NormalizedItem, Adapter, HttpFetcher, CommandRunner
src/reachstore/adapters/rss.py       RSS/Atom via feedparser
src/reachstore/adapters/github.py    GitHub releases via the gh CLI
src/reachstore/adapters/web.py       Web pages via Jina Reader
src/reachstore/adapters/registry.py  kind -> adapter wiring

tests/conftest.py                    Database fixtures, fake dependencies
tests/fixtures/rss_sample.xml        Recorded RSS feed
tests/fixtures/github_releases.json  Recorded `gh api` output
tests/fixtures/jina_page.txt         Recorded Jina Reader output
tests/test_schema.py                 Migration applies, tables exist
tests/test_store.py                  Upsert idempotency, raw payload writing
tests/test_query_isolation.py        Tenant isolation across every query function
tests/test_query_search.py           Full-text search behavior
tests/test_adapter_rss.py            RSS parsing against fixture
tests/test_adapter_github.py         GitHub parsing against fixture
tests/test_adapter_web.py            Web page parsing against fixture
tests/test_collect.py                Failure isolation, backoff, circuit breaker
tests/test_cli.py                    CLI wiring end to end
```

**Responsibility boundaries:** `store.py` writes, `query.py` reads, `collect.py` orchestrates and never touches SQL directly, adapters know one platform each and nothing about the database.

---

### Task 1: Project scaffold, schema, and migrations

**Files:**
- Create: `pyproject.toml`, `docker-compose.dev.yml`, `.env.example`, `.gitignore`
- Create: `alembic.ini`, `migrations/env.py`, `migrations/versions/0001_initial.py`
- Create: `src/reachstore/__init__.py`, `src/reachstore/config.py`, `src/reachstore/db.py`, `src/reachstore/models.py`
- Test: `tests/conftest.py`, `tests/test_schema.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces:
  - `reachstore.config.Settings` with fields `database_url: str`, `test_database_url: str`, `raw_dir: Path`; module function `get_settings() -> Settings`
  - `reachstore.db.make_engine(url: str) -> Engine`, `reachstore.db.make_session_factory(engine: Engine) -> sessionmaker[Session]`
  - `reachstore.models.Base`, and models `User`, `Collector`, `Source`, `Subscription`, `Item`, `FetchRun`, `ItemTag`
  - pytest fixtures `engine`, `session`, `raw_dir`

- [ ] **Step 1: Initialize the repository**

```bash
git init
git branch -M main
```

- [ ] **Step 2: Create `.gitignore`**

```gitignore
__pycache__/
*.py[cod]
.venv/
venv/
.env
data/
.pytest_cache/
dist/
build/
*.egg-info/
node_modules/
```

- [ ] **Step 3: Create `pyproject.toml`**

```toml
[project]
name = "reachstore"
version = "0.1.0"
description = "Persistent knowledge store for content collected via Agent-Reach"
requires-python = ">=3.11"
dependencies = [
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "psycopg[binary]>=3.1",
    "pydantic-settings>=2.2",
    "feedparser>=6.0",
    "httpx>=0.27",
    "typer>=0.12",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-cov>=5.0"]

[project.scripts]
reachstore = "reachstore.cli:app"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v"
```

- [ ] **Step 4: Create `docker-compose.dev.yml`**

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: reachstore
      POSTGRES_PASSWORD: reachstore
      POSTGRES_DB: reachstore
    ports:
      - "5433:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

Port 5433 avoids colliding with any Postgres already running on 5432.

- [ ] **Step 5: Create `.env.example`**

```bash
# Primary database
DATABASE_URL=postgresql+psycopg://reachstore:reachstore@localhost:5433/reachstore
# Separate database used by the test suite; it is dropped and recreated freely
TEST_DATABASE_URL=postgresql+psycopg://reachstore:reachstore@localhost:5433/reachstore_test
# Where raw upstream payloads are written
RAW_DIR=./data/raw
```

- [ ] **Step 6: Start Postgres and create the test database**

```bash
docker compose -f docker-compose.dev.yml up -d
cp .env.example .env
docker compose -f docker-compose.dev.yml exec postgres \
  psql -U reachstore -d reachstore -c "CREATE DATABASE reachstore_test OWNER reachstore;"
```

Expected: `CREATE DATABASE`

- [ ] **Step 7: Install the package**

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

- [ ] **Step 8: Create `src/reachstore/config.py`**

```python
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    test_database_url: str = ""
    raw_dir: Path = Path("./data/raw")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

- [ ] **Step 9: Create `src/reachstore/db.py`**

```python
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
```

- [ ] **Step 10: Create `src/reachstore/models.py`**

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TSV_EXPRESSION = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', coalesce(content_text, '')), 'B')"
)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text, default="")
    llm_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    llm_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Collector(Base):
    __tablename__ = "collectors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(Text)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("kind", "identifier", name="uq_sources_kind_identifier"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(40))
    identifier: Mapped[str] = mapped_column(Text)
    tier: Mapped[int] = mapped_column(Integer)
    config_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "source_id", name="uq_subscriptions_user_source"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("source_id", "external_id", name="uq_items_source_external"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    external_id: Mapped[str] = mapped_column(Text)
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_handle: Mapped[str | None] = mapped_column(String(200), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content_text: Mapped[str] = mapped_column(Text)
    raw_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed(TSV_EXPRESSION, persisted=True), nullable=True
    )


class FetchRun(Base):
    __tablename__ = "fetch_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    collector_id: Mapped[int | None] = mapped_column(
        ForeignKey("collectors.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    items_found: Mapped[int] = mapped_column(Integer, default=0)
    items_new: Mapped[int] = mapped_column(Integer, default=0)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)


class ItemTag(Base):
    __tablename__ = "item_tags"

    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tag: Mapped[str] = mapped_column(String(80), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

`content_tsv` is declared with `Computed(..., persisted=True)`, which tells SQLAlchemy the database maintains this column: it is never included in INSERT or UPDATE statements, but is fully usable in queries as `Item.content_tsv`. This is what lets Task 3 write the search filter in ORM terms instead of raw SQL strings.

- [ ] **Step 11: Create `alembic.ini`**

```ini
[alembic]
script_location = migrations
prepend_sys_path = src

[loggers]
keys = root

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

- [ ] **Step 12: Create `migrations/env.py`**

```python
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from reachstore.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ["DATABASE_URL"]
config.set_main_option("sqlalchemy.url", url)


def run_migrations_offline() -> None:
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

`ALEMBIC_DATABASE_URL` lets the test suite point migrations at the test database without touching `.env`.

- [ ] **Step 13: Create `migrations/versions/0001_initial.py`**

```python
"""initial schema

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False, server_default=""),
        sa.Column("llm_provider", sa.String(40), nullable=True),
        sa.Column("llm_key_encrypted", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "collectors",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("token_hash", sa.Text, nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "sources",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("identifier", sa.Text, nullable=False),
        sa.Column("tier", sa.Integer, nullable=False),
        sa.Column("config_json", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kind", "identifier", name="uq_sources_kind_identifier"),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.BigInteger, sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(120), nullable=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "source_id", name="uq_subscriptions_user_source"),
    )

    op.create_table(
        "items",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.BigInteger, sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.Text, nullable=False),
        sa.Column("owner_user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("author_handle", sa.String(200), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_text", sa.Text, nullable=False),
        sa.Column("raw_path", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "content_tsv",
            postgresql.TSVECTOR,
            sa.Computed(
                "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
                "setweight(to_tsvector('english', coalesce(content_text, '')), 'B')",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.UniqueConstraint("source_id", "external_id", name="uq_items_source_external"),
    )

    op.create_table(
        "fetch_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.BigInteger, sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("collector_id", sa.BigInteger, sa.ForeignKey("collectors.id", ondelete="SET NULL"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("items_found", sa.Integer, nullable=False, server_default="0"),
        sa.Column("items_new", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_text", sa.Text, nullable=True),
    )

    op.create_table(
        "item_tags",
        sa.Column("item_id", sa.BigInteger, sa.ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag", sa.String(80), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.execute("CREATE INDEX items_content_tsv_idx ON items USING GIN (content_tsv)")
    op.execute("CREATE INDEX items_source_published_idx ON items (source_id, published_at DESC)")
    op.execute("CREATE INDEX fetch_runs_source_started_idx ON fetch_runs (source_id, started_at DESC)")


def downgrade() -> None:
    op.drop_table("item_tags")
    op.drop_table("fetch_runs")
    op.drop_table("items")
    op.drop_table("subscriptions")
    op.drop_table("sources")
    op.drop_table("collectors")
    op.drop_table("users")
```

- [ ] **Step 14: Create `tests/conftest.py`**

```python
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
```

- [ ] **Step 15: Write the failing schema test**

Create `tests/test_schema.py`:

```python
from sqlalchemy import text

EXPECTED_TABLES = {
    "users",
    "collectors",
    "sources",
    "subscriptions",
    "items",
    "fetch_runs",
    "item_tags",
}


def test_all_tables_exist(session):
    rows = session.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    ).scalars().all()
    assert EXPECTED_TABLES.issubset(set(rows))


def test_items_has_generated_tsvector_column(session):
    row = session.execute(
        text(
            "SELECT is_generated FROM information_schema.columns "
            "WHERE table_name = 'items' AND column_name = 'content_tsv'"
        )
    ).scalar_one()
    assert row == "ALWAYS"


def test_tsvector_index_exists(session):
    names = session.execute(
        text("SELECT indexname FROM pg_indexes WHERE tablename = 'items'")
    ).scalars().all()
    assert "items_content_tsv_idx" in names
```

- [ ] **Step 16: Run the tests**

Run: `.venv/bin/pytest tests/test_schema.py -v`
Expected: PASS (3 passed). If migrations were wrong, failures name the missing table or column.

- [ ] **Step 17: Commit**

```bash
git add -A
git commit -m "feat: project scaffold, schema, and migrations"
```

---

### Task 2: Store layer with idempotent upserts

**Files:**
- Create: `src/reachstore/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `reachstore.models` (Task 1)
- Produces:
  - `reachstore.store.upsert_items(session, *, source_id: int, items: Sequence[NormalizedItem], owner_user_id: int | None, raw_dir: Path, now: datetime) -> int` returning the count of newly inserted rows
  - `reachstore.store.content_hash(text: str) -> str`
  - Depends on `NormalizedItem`, defined in Task 4's `adapters/base.py`. **Task 2 defines it first** in `adapters/base.py` (Step 1 below); Task 4 extends that file rather than creating it.

- [ ] **Step 1: Create `src/reachstore/adapters/__init__.py` and the shared item type**

Create `src/reachstore/adapters/__init__.py` as an empty file, then `src/reachstore/adapters/base.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class NormalizedItem:
    """Platform-agnostic item. Every adapter emits exactly this shape."""

    external_id: str
    url: str
    content_text: str
    title: str | None = None
    author_handle: str | None = None
    published_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 2: Write the failing store tests**

Create `tests/test_store.py`:

```python
import json
from datetime import UTC, datetime

from sqlalchemy import func, select

from reachstore.adapters.base import NormalizedItem
from reachstore.models import Item, Source, User
from reachstore.store import upsert_items

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def make_source(session) -> Source:
    source = Source(kind="rss", identifier="https://example.com/feed", tier=1, config_json={}, created_at=NOW)
    session.add(source)
    session.flush()
    return source


def make_user(session, email: str) -> User:
    user = User(email=email, display_name=email.split("@")[0], created_at=NOW)
    session.add(user)
    session.flush()
    return user


def sample_items() -> list[NormalizedItem]:
    return [
        NormalizedItem(
            external_id="post-1",
            url="https://example.com/1",
            title="First post",
            content_text="hello world",
            published_at=NOW,
            raw={"id": "post-1"},
        ),
        NormalizedItem(
            external_id="post-2",
            url="https://example.com/2",
            title="Second post",
            content_text="goodbye world",
            published_at=NOW,
            raw={"id": "post-2"},
        ),
    ]


def test_upsert_inserts_new_items(session, raw_dir):
    source = make_source(session)
    new_count = upsert_items(
        session, source_id=source.id, items=sample_items(), owner_user_id=None, raw_dir=raw_dir, now=NOW
    )
    assert new_count == 2
    assert session.execute(select(func.count()).select_from(Item)).scalar_one() == 2


def test_upsert_is_idempotent(session, raw_dir):
    source = make_source(session)
    upsert_items(session, source_id=source.id, items=sample_items(), owner_user_id=None, raw_dir=raw_dir, now=NOW)
    second = upsert_items(
        session, source_id=source.id, items=sample_items(), owner_user_id=None, raw_dir=raw_dir, now=NOW
    )
    assert second == 0
    assert session.execute(select(func.count()).select_from(Item)).scalar_one() == 2


def test_upsert_writes_raw_payload_to_disk(session, raw_dir):
    source = make_source(session)
    upsert_items(session, source_id=source.id, items=sample_items()[:1], owner_user_id=None, raw_dir=raw_dir, now=NOW)
    item = session.execute(select(Item)).scalars().one()
    assert item.raw_path is not None
    saved = json.loads((raw_dir / item.raw_path).read_text())
    assert saved == {"id": "post-1"}


def test_upsert_records_owner_for_private_items(session, raw_dir):
    source = make_source(session)
    user = make_user(session, "a@example.com")
    upsert_items(
        session, source_id=source.id, items=sample_items(), owner_user_id=user.id, raw_dir=raw_dir, now=NOW
    )
    owners = session.execute(select(Item.owner_user_id)).scalars().all()
    assert owners == [user.id, user.id]


def test_same_external_id_different_sources_are_distinct(session, raw_dir):
    source_a = make_source(session)
    source_b = Source(kind="rss", identifier="https://other.com/feed", tier=1, config_json={}, created_at=NOW)
    session.add(source_b)
    session.flush()
    upsert_items(session, source_id=source_a.id, items=sample_items(), owner_user_id=None, raw_dir=raw_dir, now=NOW)
    upsert_items(session, source_id=source_b.id, items=sample_items(), owner_user_id=None, raw_dir=raw_dir, now=NOW)
    assert session.execute(select(func.count()).select_from(Item)).scalar_one() == 4
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reachstore.store'`

- [ ] **Step 4: Implement `src/reachstore/store.py`**

```python
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from reachstore.adapters.base import NormalizedItem
from reachstore.models import Item


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_raw(raw_dir: Path, source_id: int, digest: str, raw: dict) -> str:
    """Write the upstream payload to disk. Returns a path relative to raw_dir."""
    relative = Path(str(source_id)) / f"{digest}.json"
    target = raw_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(raw, ensure_ascii=False, default=str))
    return str(relative)


def upsert_items(
    session: Session,
    *,
    source_id: int,
    items: Sequence[NormalizedItem],
    owner_user_id: int | None,
    raw_dir: Path,
    now: datetime,
) -> int:
    """Insert items, skipping any that already exist. Returns the number inserted.

    Safe to call repeatedly with the same input: (source_id, external_id) is unique
    and conflicts are ignored.
    """
    inserted = 0
    for item in items:
        digest = content_hash(item.content_text)
        raw_path = _write_raw(raw_dir, source_id, digest, item.raw) if item.raw else None
        stmt = (
            insert(Item)
            .values(
                source_id=source_id,
                external_id=item.external_id,
                owner_user_id=owner_user_id,
                url=item.url,
                title=item.title,
                author_handle=item.author_handle,
                published_at=item.published_at,
                fetched_at=now,
                content_text=item.content_text,
                raw_path=raw_path,
                content_hash=digest,
            )
            .on_conflict_do_nothing(constraint="uq_items_source_external")
            .returning(Item.id)
        )
        if session.execute(stmt).scalar_one_or_none() is not None:
            inserted += 1
    session.flush()
    return inserted
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_store.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: idempotent item store with raw payload persistence"
```

---

### Task 3: Query layer with tenant isolation

**Files:**
- Create: `src/reachstore/query.py`
- Test: `tests/test_query_isolation.py`, `tests/test_query_search.py`

**Interfaces:**
- Consumes: `reachstore.models` (Task 1), `reachstore.store.upsert_items` (Task 2, used by tests)
- Produces:
  - `reachstore.query.visible_to(user_id: int)` returning a SQLAlchemy boolean clause
  - `reachstore.query.get_item(session, *, user_id: int, item_id: int) -> Item | None`
  - `reachstore.query.feed(session, *, user_id: int, limit: int = 50, before_id: int | None = None) -> list[Item]`
  - `reachstore.query.search(session, *, user_id: int, q: str, kinds: Sequence[str] | None = None, since: datetime | None = None, subscribed_only: bool = False, limit: int = 50) -> list[Item]`

- [ ] **Step 1: Write the failing isolation tests**

Create `tests/test_query_isolation.py`:

```python
from datetime import UTC, datetime

from reachstore.adapters.base import NormalizedItem
from reachstore.models import Source, Subscription, User
from reachstore.query import feed, get_item, search
from reachstore.store import upsert_items

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def setup_two_users_with_private_items(session, raw_dir):
    alice = User(email="alice@example.com", display_name="alice", created_at=NOW)
    bob = User(email="bob@example.com", display_name="bob", created_at=NOW)
    session.add_all([alice, bob])
    session.flush()

    source = Source(kind="x_account", identifier="@someone", tier=2, config_json={}, created_at=NOW)
    shared = Source(kind="rss", identifier="https://example.com/feed", tier=1, config_json={}, created_at=NOW)
    session.add_all([source, shared])
    session.flush()

    upsert_items(
        session,
        source_id=source.id,
        items=[NormalizedItem(external_id="a1", url="https://x/1", title="alice secret", content_text="alpha")],
        owner_user_id=alice.id,
        raw_dir=raw_dir,
        now=NOW,
    )
    upsert_items(
        session,
        source_id=shared.id,
        items=[NormalizedItem(external_id="b1", url="https://x/2", title="bob secret", content_text="alpha")],
        owner_user_id=bob.id,
        raw_dir=raw_dir,
        now=NOW,
    )
    upsert_items(
        session,
        source_id=shared.id,
        items=[NormalizedItem(external_id="s1", url="https://x/3", title="public news", content_text="alpha")],
        owner_user_id=None,
        raw_dir=raw_dir,
        now=NOW,
    )
    session.add(Subscription(user_id=alice.id, source_id=shared.id, active=True, created_at=NOW))
    session.flush()
    return alice, bob


def test_feed_excludes_other_users_private_items(session, raw_dir):
    alice, bob = setup_two_users_with_private_items(session, raw_dir)
    titles = {item.title for item in feed(session, user_id=alice.id)}
    assert "alice secret" in titles
    assert "public news" in titles
    assert "bob secret" not in titles


def test_search_excludes_other_users_private_items(session, raw_dir):
    alice, bob = setup_two_users_with_private_items(session, raw_dir)
    titles = {item.title for item in search(session, user_id=alice.id, q="alpha")}
    assert titles == {"alice secret", "public news"}


def test_get_item_refuses_other_users_private_item(session, raw_dir):
    alice, bob = setup_two_users_with_private_items(session, raw_dir)
    bobs_item = next(i for i in feed(session, user_id=bob.id) if i.title == "bob secret")
    assert get_item(session, user_id=alice.id, item_id=bobs_item.id) is None
    assert get_item(session, user_id=bob.id, item_id=bobs_item.id) is not None


def test_subscribed_only_limits_to_subscribed_sources(session, raw_dir):
    alice, bob = setup_two_users_with_private_items(session, raw_dir)
    titles = {item.title for item in search(session, user_id=alice.id, q="alpha", subscribed_only=True)}
    assert titles == {"public news"}
```

- [ ] **Step 2: Write the failing search tests**

Create `tests/test_query_search.py`:

```python
from datetime import UTC, datetime, timedelta

from reachstore.adapters.base import NormalizedItem
from reachstore.models import Source, User
from reachstore.query import search
from reachstore.store import upsert_items

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def seed(session, raw_dir):
    user = User(email="u@example.com", display_name="u", created_at=NOW)
    session.add(user)
    session.flush()
    rss = Source(kind="rss", identifier="https://a/feed", tier=1, config_json={}, created_at=NOW)
    gh = Source(kind="github_repo", identifier="octo/repo", tier=1, config_json={}, created_at=NOW)
    session.add_all([rss, gh])
    session.flush()
    upsert_items(
        session,
        source_id=rss.id,
        items=[
            NormalizedItem(
                external_id="1",
                url="https://a/1",
                title="Postgres full text search",
                content_text="indexing documents with tsvector",
                published_at=NOW,
            ),
            NormalizedItem(
                external_id="2",
                url="https://a/2",
                title="Unrelated cooking post",
                content_text="how to roast garlic",
                published_at=NOW - timedelta(days=30),
            ),
        ],
        owner_user_id=None,
        raw_dir=raw_dir,
        now=NOW,
    )
    upsert_items(
        session,
        source_id=gh.id,
        items=[
            NormalizedItem(
                external_id="3",
                url="https://gh/3",
                title="Release v2 indexing",
                content_text="faster tsvector indexing",
                published_at=NOW,
            )
        ],
        owner_user_id=None,
        raw_dir=raw_dir,
        now=NOW,
    )
    return user


def test_search_matches_content_and_title(session, raw_dir):
    user = seed(session, raw_dir)
    titles = {i.title for i in search(session, user_id=user.id, q="tsvector")}
    assert titles == {"Postgres full text search", "Release v2 indexing"}


def test_search_ignores_non_matching_documents(session, raw_dir):
    user = seed(session, raw_dir)
    titles = {i.title for i in search(session, user_id=user.id, q="garlic")}
    assert titles == {"Unrelated cooking post"}


def test_search_filters_by_kind(session, raw_dir):
    user = seed(session, raw_dir)
    titles = {i.title for i in search(session, user_id=user.id, q="indexing", kinds=["github_repo"])}
    assert titles == {"Release v2 indexing"}


def test_search_filters_by_since(session, raw_dir):
    user = seed(session, raw_dir)
    results = search(session, user_id=user.id, q="roast", since=NOW - timedelta(days=1))
    assert results == []


def test_search_ranks_title_matches_above_body_matches(session, raw_dir):
    user = seed(session, raw_dir)
    results = search(session, user_id=user.id, q="indexing")
    assert results[0].title == "Release v2 indexing"
```

The last test relies on the `setweight(..., 'A')` on titles from Task 1's migration.

- [ ] **Step 3: Run both test files to verify they fail**

Run: `.venv/bin/pytest tests/test_query_isolation.py tests/test_query_search.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reachstore.query'`

- [ ] **Step 4: Implement `src/reachstore/query.py`**

```python
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, and_, desc, func, or_, select
from sqlalchemy.orm import Session

from reachstore.models import Item, Source, Subscription


def visible_to(user_id: int) -> ColumnElement[bool]:
    """The one and only tenant-isolation predicate.

    An item is visible when it is shared (owner_user_id IS NULL) or owned by this user.
    Every read path must apply this.
    """
    return or_(Item.owner_user_id.is_(None), Item.owner_user_id == user_id)


def get_item(session: Session, *, user_id: int, item_id: int) -> Item | None:
    stmt = select(Item).where(Item.id == item_id, visible_to(user_id))
    return session.execute(stmt).scalars().one_or_none()


def feed(
    session: Session, *, user_id: int, limit: int = 50, before_id: int | None = None
) -> list[Item]:
    stmt = select(Item).where(visible_to(user_id))
    if before_id is not None:
        stmt = stmt.where(Item.id < before_id)
    stmt = stmt.order_by(desc(Item.published_at.nulls_last()), desc(Item.id)).limit(limit)
    return list(session.execute(stmt).scalars().all())


def search(
    session: Session,
    *,
    user_id: int,
    q: str,
    kinds: Sequence[str] | None = None,
    since: datetime | None = None,
    subscribed_only: bool = False,
    limit: int = 50,
) -> list[Item]:
    tsquery = func.websearch_to_tsquery("english", q)
    rank = func.ts_rank(Item.content_tsv, tsquery)

    conditions = [visible_to(user_id), Item.content_tsv.bool_op("@@")(tsquery)]
    if since is not None:
        conditions.append(Item.published_at >= since)

    stmt = select(Item)
    if kinds or subscribed_only:
        stmt = stmt.join(Source, Source.id == Item.source_id)
    if kinds:
        conditions.append(Source.kind.in_(list(kinds)))
    if subscribed_only:
        stmt = stmt.join(
            Subscription,
            and_(
                Subscription.source_id == Item.source_id,
                Subscription.user_id == user_id,
                Subscription.active.is_(True),
            ),
        )

    stmt = stmt.where(*conditions).order_by(desc(rank), desc(Item.id)).limit(limit)
    return list(session.execute(stmt).scalars().all())
```

`websearch_to_tsquery` accepts human search syntax (quoted phrases, `or`, `-exclusion`) and never raises on malformed input, unlike `to_tsquery`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_query_isolation.py tests/test_query_search.py -v`
Expected: PASS (9 passed)

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: query layer with tenant isolation and full-text search"
```

---

### Task 4: Adapter contract and RSS adapter

**Files:**
- Modify: `src/reachstore/adapters/base.py` (add protocols below `NormalizedItem`)
- Create: `src/reachstore/adapters/rss.py`
- Create: `tests/fixtures/rss_sample.xml`
- Test: `tests/test_adapter_rss.py`

**Interfaces:**
- Consumes: `NormalizedItem` (Task 2)
- Produces:
  - `HttpFetcher` protocol: `get(url: str, *, timeout: int) -> str`
  - `CommandRunner` protocol: `run(args: list[str], *, timeout: int) -> str`
  - `Adapter` protocol: attributes `kind: str`, `tier: int`; method `fetch(identifier: str, since: datetime | None) -> list[NormalizedItem]`
  - `HttpxFetcher` and `SubprocessRunner` concrete implementations
  - `reachstore.adapters.rss.RssAdapter(http: HttpFetcher, timeout: int = 120)`

- [ ] **Step 1: Add protocols to `src/reachstore/adapters/base.py`**

Append below the existing `NormalizedItem`:

```python
import subprocess
from typing import Protocol, runtime_checkable

import httpx


class AdapterError(RuntimeError):
    """Raised when an adapter cannot fetch or parse a source."""


@runtime_checkable
class HttpFetcher(Protocol):
    def get(self, url: str, *, timeout: int) -> str: ...


@runtime_checkable
class CommandRunner(Protocol):
    def run(self, args: list[str], *, timeout: int) -> str: ...


@runtime_checkable
class Adapter(Protocol):
    kind: str
    tier: int

    def fetch(self, identifier: str, since: datetime | None) -> list[NormalizedItem]: ...


class HttpxFetcher:
    """Real HTTP fetcher. Never used in tests."""

    def get(self, url: str, *, timeout: int) -> str:
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
        return response.text


class SubprocessRunner:
    """Real command runner for upstream CLIs installed by agent-reach. Never used in tests."""

    def run(self, args: list[str], *, timeout: int) -> str:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            raise AdapterError(f"{args[0]} failed ({result.returncode}): {result.stderr.strip()}")
        return result.stdout
```

- [ ] **Step 2: Create `tests/fixtures/rss_sample.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Blog</title>
    <link>https://example.com</link>
    <item>
      <title>Understanding tsvector</title>
      <link>https://example.com/posts/tsvector</link>
      <guid>https://example.com/posts/tsvector</guid>
      <author>editor@example.com (Sam Rivers)</author>
      <pubDate>Tue, 12 Aug 2026 09:30:00 +0000</pubDate>
      <description>A practical look at Postgres full-text search internals.</description>
    </item>
    <item>
      <title>Scaling collectors</title>
      <link>https://example.com/posts/collectors</link>
      <guid>https://example.com/posts/collectors</guid>
      <pubDate>Mon, 04 Aug 2026 17:00:00 +0000</pubDate>
      <description>Why residential IPs matter for scraping.</description>
    </item>
  </channel>
</rss>
```

- [ ] **Step 3: Write the failing RSS adapter test**

Create `tests/test_adapter_rss.py`:

```python
from datetime import UTC, datetime

import pytest

from reachstore.adapters.base import AdapterError
from reachstore.adapters.rss import RssAdapter


class FakeHttp:
    def __init__(self, body: str):
        self.body = body
        self.calls: list[str] = []

    def get(self, url: str, *, timeout: int) -> str:
        self.calls.append(url)
        return self.body


@pytest.fixture
def adapter(fixtures_dir):
    return RssAdapter(FakeHttp((fixtures_dir / "rss_sample.xml").read_text()))


def test_kind_and_tier(adapter):
    assert adapter.kind == "rss"
    assert adapter.tier == 1


def test_parses_all_entries(adapter):
    items = adapter.fetch("https://example.com/feed", None)
    assert len(items) == 2


def test_maps_fields_correctly(adapter):
    first = adapter.fetch("https://example.com/feed", None)[0]
    assert first.external_id == "https://example.com/posts/tsvector"
    assert first.url == "https://example.com/posts/tsvector"
    assert first.title == "Understanding tsvector"
    assert first.author_handle == "editor@example.com (Sam Rivers)"
    assert first.published_at == datetime(2026, 8, 12, 9, 30, tzinfo=UTC)
    assert "full-text search" in first.content_text
    assert first.raw["link"] == "https://example.com/posts/tsvector"


def test_since_filters_older_entries(adapter):
    items = adapter.fetch("https://example.com/feed", datetime(2026, 8, 10, tzinfo=UTC))
    assert [i.title for i in items] == ["Understanding tsvector"]


def test_missing_author_is_none(adapter):
    second = adapter.fetch("https://example.com/feed", None)[1]
    assert second.author_handle is None


def test_unparseable_body_raises_adapter_error():
    adapter = RssAdapter(FakeHttp("this is not a feed at all"))
    with pytest.raises(AdapterError):
        adapter.fetch("https://example.com/feed", None)
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_adapter_rss.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reachstore.adapters.rss'`

- [ ] **Step 5: Implement `src/reachstore/adapters/rss.py`**

```python
from __future__ import annotations

from datetime import UTC, datetime
from time import struct_time

import feedparser

from reachstore.adapters.base import AdapterError, HttpFetcher, NormalizedItem


def _to_datetime(parsed: struct_time | None) -> datetime | None:
    if parsed is None:
        return None
    return datetime(*parsed[:6], tzinfo=UTC)


class RssAdapter:
    kind = "rss"
    tier = 1

    def __init__(self, http: HttpFetcher, timeout: int = 120):
        self._http = http
        self._timeout = timeout

    def fetch(self, identifier: str, since: datetime | None) -> list[NormalizedItem]:
        body = self._http.get(identifier, timeout=self._timeout)
        feed = feedparser.parse(body)
        if not feed.entries:
            raise AdapterError(f"no entries parsed from {identifier}")

        items: list[NormalizedItem] = []
        for entry in feed.entries:
            published = _to_datetime(entry.get("published_parsed") or entry.get("updated_parsed"))
            if since is not None and published is not None and published < since:
                continue
            link = entry.get("link", "")
            items.append(
                NormalizedItem(
                    external_id=entry.get("id") or link,
                    url=link,
                    title=entry.get("title"),
                    author_handle=entry.get("author"),
                    published_at=published,
                    content_text=entry.get("summary", ""),
                    raw=dict(entry),
                )
            )
        return items
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_adapter_rss.py -v`
Expected: PASS (6 passed)

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: adapter contract and RSS adapter"
```

---

### Task 5: GitHub adapter

**Files:**
- Create: `src/reachstore/adapters/github.py`
- Create: `tests/fixtures/github_releases.json`
- Test: `tests/test_adapter_github.py`

**Interfaces:**
- Consumes: `CommandRunner`, `NormalizedItem`, `AdapterError` (Task 4)
- Produces: `reachstore.adapters.github.GithubRepoAdapter(runner: CommandRunner, timeout: int = 120)`

The adapter shells out to the `gh` CLI that Agent-Reach installs and authenticates:
`gh api repos/{owner}/{repo}/releases --paginate`

- [ ] **Step 1: Create `tests/fixtures/github_releases.json`**

```json
[
  {
    "id": 900001,
    "tag_name": "v2.1.0",
    "name": "v2.1.0 — faster indexing",
    "html_url": "https://github.com/octo/repo/releases/tag/v2.1.0",
    "published_at": "2026-08-11T08:00:00Z",
    "author": { "login": "octocat" },
    "body": "Rewrote the indexer. Cuts collection time by half."
  },
  {
    "id": 890002,
    "tag_name": "v2.0.0",
    "name": "v2.0.0",
    "html_url": "https://github.com/octo/repo/releases/tag/v2.0.0",
    "published_at": "2026-07-02T10:15:00Z",
    "author": { "login": "hubber" },
    "body": "Breaking: renamed the CLI entrypoint."
  }
]
```

- [ ] **Step 2: Write the failing GitHub adapter test**

Create `tests/test_adapter_github.py`:

```python
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
    with pytest.raises(AdapterError):
        GithubRepoAdapter(FakeRunner("[]")).fetch("repo-only", None)


def test_invalid_json_raises_adapter_error():
    with pytest.raises(AdapterError):
        GithubRepoAdapter(FakeRunner("not json")).fetch("octo/repo", None)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_adapter_github.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reachstore.adapters.github'`

- [ ] **Step 4: Implement `src/reachstore/adapters/github.py`**

```python
from __future__ import annotations

import json
from datetime import datetime

from reachstore.adapters.base import AdapterError, CommandRunner, NormalizedItem


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class GithubRepoAdapter:
    """Collects releases from a GitHub repository via the gh CLI."""

    kind = "github_repo"
    tier = 1

    def __init__(self, runner: CommandRunner, timeout: int = 120):
        self._runner = runner
        self._timeout = timeout

    def fetch(self, identifier: str, since: datetime | None) -> list[NormalizedItem]:
        if identifier.count("/") != 1:
            raise AdapterError(f"expected 'owner/repo', got {identifier!r}")

        raw = self._runner.run(
            ["gh", "api", f"repos/{identifier}/releases", "--paginate"], timeout=self._timeout
        )
        try:
            releases = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AdapterError(f"gh returned unparseable JSON for {identifier}: {exc}") from exc

        items: list[NormalizedItem] = []
        for release in releases:
            published = _parse_iso(release.get("published_at"))
            if since is not None and published is not None and published < since:
                continue
            items.append(
                NormalizedItem(
                    external_id=str(release["id"]),
                    url=release.get("html_url", ""),
                    title=release.get("name") or release.get("tag_name"),
                    author_handle=(release.get("author") or {}).get("login"),
                    published_at=published,
                    content_text=release.get("body") or "",
                    raw=release,
                )
            )
        return items
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_adapter_github.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: GitHub releases adapter via gh CLI"
```

---

### Task 6: Web page adapter and registry

**Files:**
- Create: `src/reachstore/adapters/web.py`, `src/reachstore/adapters/registry.py`
- Create: `tests/fixtures/jina_page.txt`
- Test: `tests/test_adapter_web.py`

**Interfaces:**
- Consumes: `HttpFetcher`, `NormalizedItem`, `AdapterError` (Task 4), `RssAdapter` (Task 4), `GithubRepoAdapter` (Task 5)
- Produces:
  - `reachstore.adapters.web.WebPageAdapter(http: HttpFetcher, timeout: int = 120)`
  - `reachstore.adapters.registry.build_registry(http: HttpFetcher, runner: CommandRunner) -> dict[str, Adapter]`

A web page yields at most one item per fetch. Its `external_id` is the SHA-256 of the extracted text, so an unchanged page re-collects to zero new rows while an edited page produces a new item — a natural change log.

- [ ] **Step 1: Create `tests/fixtures/jina_page.txt`**

```
Title: How residential IPs affect scraping

URL Source: https://example.com/articles/residential-ips

Markdown Content:
Datacenter address ranges are registered publicly, so platforms can classify
traffic before inspecting it. Requests from hosting providers face tighter
limits than requests from consumer ISPs.
```

- [ ] **Step 2: Write the failing web adapter test**

Create `tests/test_adapter_web.py`:

```python
import hashlib

import pytest

from reachstore.adapters.base import AdapterError
from reachstore.adapters.registry import build_registry
from reachstore.adapters.web import WebPageAdapter


class FakeHttp:
    def __init__(self, body: str):
        self.body = body
        self.calls: list[str] = []

    def get(self, url: str, *, timeout: int) -> str:
        self.calls.append(url)
        return self.body


class FakeRunner:
    def run(self, args: list[str], *, timeout: int) -> str:
        return "[]"


@pytest.fixture
def http(fixtures_dir):
    return FakeHttp((fixtures_dir / "jina_page.txt").read_text())


def test_fetches_through_jina_reader(http):
    WebPageAdapter(http).fetch("https://example.com/articles/residential-ips", None)
    assert http.calls == ["https://r.jina.ai/https://example.com/articles/residential-ips"]


def test_returns_single_item_with_extracted_title(http):
    items = WebPageAdapter(http).fetch("https://example.com/articles/residential-ips", None)
    assert len(items) == 1
    assert items[0].title == "How residential IPs affect scraping"
    assert items[0].url == "https://example.com/articles/residential-ips"
    assert "consumer ISPs" in items[0].content_text


def test_external_id_is_content_hash(http):
    item = WebPageAdapter(http).fetch("https://example.com/articles/residential-ips", None)[0]
    assert item.external_id == hashlib.sha256(item.content_text.encode()).hexdigest()


def test_unchanged_page_produces_identical_external_id(http):
    a = WebPageAdapter(http).fetch("https://example.com/x", None)[0]
    b = WebPageAdapter(http).fetch("https://example.com/x", None)[0]
    assert a.external_id == b.external_id


def test_empty_body_raises_adapter_error():
    with pytest.raises(AdapterError):
        WebPageAdapter(FakeHttp("   ")).fetch("https://example.com/x", None)


def test_registry_exposes_all_tier1_kinds(http):
    registry = build_registry(http, FakeRunner())
    assert set(registry) == {"rss", "github_repo", "web_page"}
    assert all(adapter.tier == 1 for adapter in registry.values())
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_adapter_web.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reachstore.adapters.web'`

- [ ] **Step 4: Implement `src/reachstore/adapters/web.py`**

```python
from __future__ import annotations

import hashlib
from datetime import datetime

from reachstore.adapters.base import AdapterError, HttpFetcher, NormalizedItem

JINA_PREFIX = "https://r.jina.ai/"


def _extract_title(body: str) -> str | None:
    for line in body.splitlines():
        if line.startswith("Title:"):
            return line.removeprefix("Title:").strip()
    return None


def _extract_content(body: str) -> str:
    marker = "Markdown Content:"
    if marker in body:
        return body.split(marker, 1)[1].strip()
    return body.strip()


class WebPageAdapter:
    """Reads a single web page through Jina Reader.

    Yields at most one item. The external_id is the content hash, so an unchanged
    page collects to zero new rows and an edited page produces a new item.
    """

    kind = "web_page"
    tier = 1

    def __init__(self, http: HttpFetcher, timeout: int = 120):
        self._http = http
        self._timeout = timeout

    def fetch(self, identifier: str, since: datetime | None) -> list[NormalizedItem]:
        body = self._http.get(f"{JINA_PREFIX}{identifier}", timeout=self._timeout)
        content = _extract_content(body)
        if not content.strip():
            raise AdapterError(f"empty content returned for {identifier}")
        return [
            NormalizedItem(
                external_id=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                url=identifier,
                title=_extract_title(body),
                author_handle=None,
                published_at=None,
                content_text=content,
                raw={"body": body},
            )
        ]
```

- [ ] **Step 5: Implement `src/reachstore/adapters/registry.py`**

```python
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
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_adapter_web.py -v`
Expected: PASS (6 passed)

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: web page adapter via Jina Reader and adapter registry"
```

---

### Task 7: Collection orchestration with failure isolation

**Files:**
- Create: `src/reachstore/collect.py`
- Modify: `src/reachstore/query.py` (append `source_health`)
- Test: `tests/test_collect.py`

**Interfaces:**
- Consumes: `upsert_items` (Task 2), `visible_to` (Task 3), registry and adapters (Tasks 4–6)
- Produces:
  - `reachstore.collect.CollectResult(source_id: int, status: str, items_found: int, items_new: int, error_text: str | None)`
  - `reachstore.collect.consecutive_failures(session, source_id: int) -> int`
  - `reachstore.collect.should_attempt(session, source_id: int, now: datetime) -> bool`
  - `reachstore.collect.collect_source(session, *, source: Source, adapter: Adapter, raw_dir: Path, now: datetime, owner_user_id: int | None = None) -> CollectResult`
  - `reachstore.collect.collect_tier(session, *, tier: int, registry: dict[str, Adapter], raw_dir: Path, now: datetime, force: bool = False) -> list[CollectResult]`
  - `reachstore.query.source_health(session, *, user_id: int) -> list[SourceStatus]` with `SourceStatus(source_id, kind, identifier, last_status, last_run_at, consecutive_failures, needs_attention)`

Backoff and the circuit breaker are **derived** from `fetch_runs` rather than stored as mutable columns — the same principle as source health in the spec.

- [ ] **Step 1: Write the failing collection tests**

Create `tests/test_collect.py`:

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from reachstore.adapters.base import AdapterError, NormalizedItem
from reachstore.collect import (
    CollectResult,
    collect_source,
    collect_tier,
    consecutive_failures,
    should_attempt,
)
from reachstore.models import FetchRun, Item, Source, User
from reachstore.query import source_health

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


class StubAdapter:
    def __init__(self, kind: str, items=None, error: Exception | None = None):
        self.kind = kind
        self.tier = 1
        self._items = items or []
        self._error = error
        self.calls = 0

    def fetch(self, identifier: str, since):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._items


def add_source(session, kind="rss", identifier="https://a/feed", tier=1) -> Source:
    source = Source(kind=kind, identifier=identifier, tier=tier, config_json={}, created_at=NOW)
    session.add(source)
    session.flush()
    return source


def one_item() -> list[NormalizedItem]:
    return [NormalizedItem(external_id="1", url="https://a/1", title="t", content_text="body")]


def test_successful_collection_stores_items_and_records_run(session, raw_dir):
    source = add_source(session)
    result = collect_source(
        session, source=source, adapter=StubAdapter("rss", one_item()), raw_dir=raw_dir, now=NOW
    )
    assert result == CollectResult(source.id, "success", 1, 1, None)
    assert session.execute(select(Item)).scalars().all()
    run = session.execute(select(FetchRun)).scalars().one()
    assert run.status == "success"
    assert run.items_new == 1
    assert run.finished_at is not None


def test_failing_adapter_records_failed_run_and_does_not_raise(session, raw_dir):
    source = add_source(session)
    result = collect_source(
        session,
        source=source,
        adapter=StubAdapter("rss", error=AdapterError("feed is gone")),
        raw_dir=raw_dir,
        now=NOW,
    )
    assert result.status == "failed"
    assert "feed is gone" in result.error_text
    run = session.execute(select(FetchRun)).scalars().one()
    assert run.status == "failed"


def test_one_failing_source_does_not_abort_the_run(session, raw_dir):
    good = add_source(session, identifier="https://good/feed")
    bad = add_source(session, identifier="https://bad/feed")
    registry = {"rss": StubAdapter("rss", one_item())}
    failing = {"rss": StubAdapter("rss", error=AdapterError("boom"))}

    results = []
    results.append(collect_source(session, source=bad, adapter=failing["rss"], raw_dir=raw_dir, now=NOW))
    results.append(collect_source(session, source=good, adapter=registry["rss"], raw_dir=raw_dir, now=NOW))
    assert [r.status for r in results] == ["failed", "success"]


def test_collect_tier_only_touches_matching_tier(session, raw_dir):
    tier1 = add_source(session, kind="rss", identifier="https://a/feed", tier=1)
    add_source(session, kind="x_account", identifier="@someone", tier=2)
    adapter = StubAdapter("rss", one_item())
    results = collect_tier(session, tier=1, registry={"rss": adapter}, raw_dir=raw_dir, now=NOW)
    assert [r.source_id for r in results] == [tier1.id]
    assert adapter.calls == 1


def test_collect_tier_skips_kinds_with_no_adapter(session, raw_dir):
    add_source(session, kind="unknown_kind", identifier="x", tier=1)
    results = collect_tier(session, tier=1, registry={}, raw_dir=raw_dir, now=NOW)
    assert results == []


def test_consecutive_failures_counts_only_the_recent_streak(session, raw_dir):
    source = add_source(session)
    for index, status in enumerate(["failed", "success", "failed", "failed"]):
        session.add(
            FetchRun(
                source_id=source.id,
                started_at=NOW - timedelta(hours=10 - index),
                finished_at=NOW - timedelta(hours=10 - index),
                status=status,
                items_found=0,
                items_new=0,
            )
        )
    session.flush()
    assert consecutive_failures(session, source.id) == 2


def test_backoff_blocks_retry_immediately_after_failure(session, raw_dir):
    source = add_source(session)
    session.add(
        FetchRun(
            source_id=source.id,
            started_at=NOW - timedelta(minutes=1),
            finished_at=NOW - timedelta(minutes=1),
            status="failed",
            items_found=0,
            items_new=0,
        )
    )
    session.flush()
    assert should_attempt(session, source.id, NOW) is False
    assert should_attempt(session, source.id, NOW + timedelta(minutes=30)) is True


def test_circuit_breaker_opens_after_five_consecutive_failures(session, raw_dir):
    source = add_source(session)
    for index in range(5):
        session.add(
            FetchRun(
                source_id=source.id,
                started_at=NOW - timedelta(days=10 - index),
                finished_at=NOW - timedelta(days=10 - index),
                status="failed",
                items_found=0,
                items_new=0,
            )
        )
    session.flush()
    assert should_attempt(session, source.id, NOW + timedelta(days=30)) is False


def test_force_overrides_the_circuit_breaker(session, raw_dir):
    source = add_source(session)
    for index in range(5):
        session.add(
            FetchRun(
                source_id=source.id,
                started_at=NOW - timedelta(days=10 - index),
                finished_at=NOW - timedelta(days=10 - index),
                status="failed",
                items_found=0,
                items_new=0,
            )
        )
    session.flush()
    adapter = StubAdapter("rss", one_item())
    results = collect_tier(
        session, tier=1, registry={"rss": adapter}, raw_dir=raw_dir, now=NOW, force=True
    )
    assert [r.status for r in results] == ["success"]


def test_source_health_reports_attention_state(session, raw_dir):
    user = User(email="u@example.com", display_name="u", created_at=NOW)
    session.add(user)
    source = add_source(session)
    session.flush()
    for index in range(5):
        session.add(
            FetchRun(
                source_id=source.id,
                started_at=NOW - timedelta(hours=5 - index),
                finished_at=NOW - timedelta(hours=5 - index),
                status="failed",
                items_found=0,
                items_new=0,
                error_text="boom",
            )
        )
    session.flush()
    statuses = source_health(session, user_id=user.id)
    assert len(statuses) == 1
    assert statuses[0].consecutive_failures == 5
    assert statuses[0].needs_attention is True
    assert statuses[0].last_status == "failed"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_collect.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reachstore.collect'`

- [ ] **Step 3: Implement `src/reachstore/collect.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from reachstore.adapters.base import Adapter
from reachstore.models import FetchRun, Item, Source
from reachstore.store import upsert_items

FAILURE_LIMIT = 5
BASE_BACKOFF = timedelta(minutes=15)
MAX_BACKOFF = timedelta(hours=24)


@dataclass(frozen=True)
class CollectResult:
    source_id: int
    status: str
    items_found: int
    items_new: int
    error_text: str | None


def consecutive_failures(session: Session, source_id: int) -> int:
    """Length of the current unbroken failure streak, newest run first."""
    statuses = session.execute(
        select(FetchRun.status)
        .where(FetchRun.source_id == source_id)
        .order_by(desc(FetchRun.started_at))
        .limit(FAILURE_LIMIT)
    ).scalars().all()
    streak = 0
    for status in statuses:
        if status != "failed":
            break
        streak += 1
    return streak


def should_attempt(session: Session, source_id: int, now: datetime) -> bool:
    """False while backing off, and permanently once the circuit breaker opens."""
    failures = consecutive_failures(session, source_id)
    if failures == 0:
        return True
    if failures >= FAILURE_LIMIT:
        return False

    last_failure_at = session.execute(
        select(FetchRun.started_at)
        .where(FetchRun.source_id == source_id, FetchRun.status == "failed")
        .order_by(desc(FetchRun.started_at))
        .limit(1)
    ).scalar_one()
    delay = min(BASE_BACKOFF * (2 ** (failures - 1)), MAX_BACKOFF)
    return now >= last_failure_at + delay


def _last_success_at(session: Session, source_id: int) -> datetime | None:
    return session.execute(
        select(FetchRun.started_at)
        .where(FetchRun.source_id == source_id, FetchRun.status == "success")
        .order_by(desc(FetchRun.started_at))
        .limit(1)
    ).scalar_one_or_none()


def collect_source(
    session: Session,
    *,
    source: Source,
    adapter: Adapter,
    raw_dir: Path,
    now: datetime,
    owner_user_id: int | None = None,
) -> CollectResult:
    """Fetch one source. Never raises: failures are recorded and returned."""
    run = FetchRun(
        source_id=source.id, started_at=now, status="running", items_found=0, items_new=0
    )
    session.add(run)
    session.flush()

    try:
        items = adapter.fetch(source.identifier, _last_success_at(session, source.id))
        new_count = upsert_items(
            session,
            source_id=source.id,
            items=items,
            owner_user_id=owner_user_id,
            raw_dir=raw_dir,
            now=now,
        )
    except Exception as exc:  # bulkhead: one source must never abort the run
        run.status = "failed"
        run.finished_at = now
        run.error_text = str(exc)
        session.flush()
        return CollectResult(source.id, "failed", 0, 0, str(exc))

    run.status = "success"
    run.finished_at = now
    run.items_found = len(items)
    run.items_new = new_count
    session.flush()
    return CollectResult(source.id, "success", len(items), new_count, None)


def collect_tier(
    session: Session,
    *,
    tier: int,
    registry: dict[str, Adapter],
    raw_dir: Path,
    now: datetime,
    force: bool = False,
) -> list[CollectResult]:
    """Collect every source in a tier, isolating failures per source."""
    sources = session.execute(select(Source).where(Source.tier == tier).order_by(Source.id)).scalars().all()

    results: list[CollectResult] = []
    for source in sources:
        adapter = registry.get(source.kind)
        if adapter is None:
            continue
        if not force and not should_attempt(session, source.id, now):
            continue
        results.append(
            collect_source(session, source=source, adapter=adapter, raw_dir=raw_dir, now=now)
        )
    return results
```

- [ ] **Step 4: Append `source_health` to `src/reachstore/query.py`**

Add these imports to the existing import block: `from dataclasses import dataclass` and `from reachstore.models import FetchRun`. Then append:

```python
@dataclass(frozen=True)
class SourceStatus:
    source_id: int
    kind: str
    identifier: str
    last_status: str | None
    last_run_at: datetime | None
    consecutive_failures: int
    needs_attention: bool


def source_health(session: Session, *, user_id: int) -> list[SourceStatus]:
    """Derive per-source health from fetch_runs. Nothing here is stored state."""
    from reachstore.collect import FAILURE_LIMIT, consecutive_failures

    sources = session.execute(select(Source).order_by(Source.id)).scalars().all()

    statuses: list[SourceStatus] = []
    for source in sources:
        last = session.execute(
            select(FetchRun)
            .where(FetchRun.source_id == source.id)
            .order_by(desc(FetchRun.started_at))
            .limit(1)
        ).scalars().one_or_none()
        failures = consecutive_failures(session, source.id)
        statuses.append(
            SourceStatus(
                source_id=source.id,
                kind=source.kind,
                identifier=source.identifier,
                last_status=last.status if last else None,
                last_run_at=last.started_at if last else None,
                consecutive_failures=failures,
                needs_attention=failures >= FAILURE_LIMIT,
            )
        )
    return statuses
```

The import of `collect` sits inside the function because `collect` imports `store`, which imports models — a module-level import here would create a cycle.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_collect.py -v`
Expected: PASS (10 passed)

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/pytest -v`
Expected: PASS (all tests from Tasks 1–7)

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: collection orchestration with failure isolation and derived health"
```

---

### Task 8: CLI entrypoint

**Files:**
- Create: `src/reachstore/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7
- Produces:
  - `reachstore.cli.app` (Typer application) with commands `add-source`, `collect`, `search`, `health`
  - `reachstore.cli.build_default_registry() -> dict[str, Adapter]` wiring the real `HttpxFetcher` and `SubprocessRunner`

This is the only module permitted to read the real clock and construct real network dependencies.

- [ ] **Step 1: Write the failing CLI test**

Create `tests/test_cli.py`:

```python
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
    assert result.exit_code == 0
    assert "failed" in result.stdout
    assert "upstream exploded" in result.stdout
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reachstore.cli'`

- [ ] **Step 3: Implement `src/reachstore/cli.py`**

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS — all tests green

- [ ] **Step 6: Verify against a real feed by hand**

```bash
.venv/bin/reachstore add-source rss https://github.blog/feed/ --tier 1
.venv/bin/reachstore collect --tier 1
```

Expected: a line reporting new items. This is the only step that touches the network.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: CLI for source management, collection, search, and health"
```

---

## Definition of done

- `pytest` passes with no network access.
- `reachstore add-source` / `collect` / `search` / `health` work against a real RSS feed and a real GitHub repository.
- Re-running `collect` immediately produces zero new items.
- Isolation tests prove no query function returns another user's private items.

## What this plan does not cover

Deferred to later plans: the JSON API and authentication (Plan 2), the collector CLI and Tier-2/3 adapters (Plan 3), the React UI and deployment (Plan 4), and `ask()` LLM synthesis (Plan 2, since it needs per-user keys from the auth layer).
