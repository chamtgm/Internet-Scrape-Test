# Auth and Subscriptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hard-coded `DEFAULT_USER_ID` with real invite-only accounts, revocable server-side sessions, and an admin role, and give the existing subscriptions table its first write path.

**Architecture:** One new module, `src/reachstore/api/auth.py`, owns everything between a cookie and an identity: password hashing, session lifecycle, invite lifecycle, and two FastAPI dependencies (`get_current_user`, `require_admin`). Every existing endpoint gains one of those dependencies; nothing else in the tree learns how authentication works. The frontend gains two screens and a conditional gate on mount — no router.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, PostgreSQL 16, Typer, React 19, Vite 8, Playwright. **No new dependency in either language.** Password hashing uses stdlib `hashlib.scrypt`; tokens use stdlib `secrets`.

**Spec:** `docs/superpowers/specs/2026-09-18-auth-and-subscriptions-design.md`

## Global Constraints

- Python 3.11 or newer. Type hints on all public functions.
- PostgreSQL 16. No SQLite fallback.
- **No network access in the Python test suite.**
- **Only entrypoints read the real clock — `cli.py` and the `api/` package. Never `query`, `collect`, `store`, or any adapter.** Functions in `auth.py` take `now: datetime` as a parameter; the route handlers and dependencies supply `datetime.now(UTC)`.
- **Each table has exactly one owning module, and only that module writes SQL against it.** Content tables — `items`, `sources`, `fetch_runs`, `item_tags` — are owned by `store.py` (writes) and `query.py` (reads). The three authentication tables — `users`, `sessions`, `invites` — are owned by `api/auth.py`.
- Tenant isolation predicate: `items.owner_user_id IS NULL OR items.owner_user_id = :user_id`, in exactly one function — `query.visible_to`. The API passes `user_id` down and must never filter by owner itself.
- Every collection operation must be idempotent. Subscribe and unsubscribe must be idempotent too, enforced by the database rather than an application-level existence check.
- Free tooling only. No paid services, no API keys.
- Timestamps are timezone-aware UTC (`TIMESTAMPTZ`).
- **No CORS middleware anywhere.**
- **The server must refuse to bind a non-loopback host** unless `REACHSTORE_ALLOW_NONLOCAL=1`.
- **The session cookie must NOT set `Secure`.** There is no HTTPS on localhost and setting it would break the cookie entirely. This is deliberate; see §9 of the spec.
- **The suite must stay warning-free.** It is currently at 116 passing with zero warnings.
- **Expected test counts in this plan are indicative, not contractual.** Trust what `pytest` reports over the number written here; if they disagree, the plan's arithmetic is the thing that is wrong. The one hard rule is that the total must never *drop* — that means a test was deleted rather than retrofitted.

### Amendment to a Plan-2 constraint, and why

Plan 2's constraint read: *"All SQL lives in `store.py` and `query.py`. The API must not import `sqlalchemy.select` or build any query."*

That is now too strong, and the spec did not notice. `auth.py` must read and write `sessions` and `invites`. Those are not content, and pushing them into `query.py` — documented as "the only reader" of items — would blur the boundary that constraint exists to protect.

The constraint is therefore restated as **one owning module per table**, above. Its purpose is unchanged: tenant isolation stays in exactly one function, and content SQL stays auditable in two files. What changes is that `auth.py` may use `select`/`delete` **against `users`, `sessions`, and `invites` only**. `routes.py` still builds no queries at all.

A reviewer finding `select(Item)` or `select(Source)` in `auth.py`, or any query in `routes.py`, should treat it as a violation.

## File Structure

```
src/reachstore/models.py                 Modify: User.is_admin; UserSession, Invite
migrations/versions/0002_auth.py         Create: one column, two tables
src/reachstore/config.py                 Modify: web_base_url setting
src/reachstore/api/auth.py               Create: the whole auth boundary
src/reachstore/api/deps.py               Modify: DELETE DEFAULT_USER_ID
src/reachstore/api/schemas.py            Modify: auth, catalog, subscription models
src/reachstore/api/routes.py             Modify: dependencies on every endpoint; 6 new
src/reachstore/cli.py                    Modify: invite, set-password, revoke-sessions

tests/conftest.py                        Modify: user/client fixtures; autouse flag reset
tests/test_auth_unit.py                  Create: passwords, sessions, invites
tests/test_api_auth.py                   Create: login, logout, me, setup
tests/test_api_permissions.py            Create: the endpoint permission matrix
tests/test_api_subscriptions.py          Create: catalog, subscribe, subscribed_only
tests/test_api_read.py                   Modify: adopt authenticated client
tests/test_api_sources.py                Modify: adopt admin client
tests/test_api_collect.py                Modify: adopt admin client
tests/test_api_tenant_http.py            Create: isolation through HTTP

web/src/components/Login.jsx             Create
web/src/components/Setup.jsx             Create
web/src/components/SubscriptionStrip.jsx Create
web/src/App.jsx                          Modify: the me gate, logout, admin gating
web/src/components/SearchBar.jsx         Modify: subscribed-only toggle
web/src/api.js                           Modify: 8 new wrappers
web/src/styles.css                       Modify: auth + strip styles
web/tests/seed_e2e.py                    Modify: seed an admin with a known password
web/tests/smoke.spec.js                  Modify: log in first
web/tests/auth.spec.js                   Create: login and setup flows

docs/architecture.md                     Modify: §3, §4, §7, §9
```

**Responsibility boundaries.** `auth.py` is the only module that turns a cookie into a `User`, and the only one that touches `users`/`sessions`/`invites`. `routes.py` translates HTTP and builds no SQL. `schemas.py` owns wire shapes. `conftest.py` owns the authenticated-client fixtures that 18 existing tests depend on.

## Existing code this plan builds on

Verified against `main` at `6e6361a`. Do not re-derive these:

```python
# src/reachstore/models.py — imports already present
from sqlalchemy import (BigInteger, Boolean, Computed, DateTime, ForeignKey,
                        Index, Integer, String, Text, UniqueConstraint, text)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class User(Base):                      # __tablename__ = "users"
    id, email(String 320, unique), display_name(String 120),
    password_hash(Text, default=""), llm_provider, llm_key_encrypted, created_at

class Subscription(Base):              # __tablename__ = "subscriptions"
    # UniqueConstraint("user_id", "source_id", name="uq_subscriptions_user_source")
    id, user_id(FK CASCADE), source_id(FK CASCADE), label, active(Boolean), created_at

# src/reachstore/query.py
search(session, *, user_id, q, kinds=None, since=None, subscribed_only=False, limit=50)
#   subscribed_only already joins Subscription on source_id + user_id + active.is_(True).
#   It has never had a caller.
feed(session, *, user_id, limit=50, before_id=None, before_published_at=None)
get_item(session, *, user_id, item_id)
source_health(session)                 # no user_id; global operator view
MAX_LIMIT = 200

# src/reachstore/api/deps.py
DEFAULT_USER_ID = 1                    # this plan deletes it
get_engine(), get_session_factory()    # both lru_cache'd
get_session() -> Iterator[Session]     # overridden in tests
raw_dir() -> Path

# src/reachstore/config.py
class Settings(BaseSettings):          # model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str; test_database_url: str = ""; raw_dir: Path = Path("./data/raw")

# src/reachstore/cli.py  — Typer; commands: add-source, collect, search, health
app = typer.Typer(help="Agent-Reach knowledge store")
def _session() -> Session: ...         # builds its own engine per invocation
```

Existing fixtures in `tests/conftest.py`: `test_database_url` (session), `engine` (session; runs `DROP SCHEMA public CASCADE` then `alembic upgrade head`), `session` (function; `join_transaction_mode="create_savepoint"`, rolled back), `raw_dir`, `fixtures_dir`.

Migration conventions from `migrations/versions/0001_initial.py`: module docstring with `Revision ID` / `Revises`, then `revision = "0001"`, `down_revision = None`, `branch_labels = None`, `depends_on = None`, `import sqlalchemy as sa`, `from alembic import op`.

---

### Task 1: Schema — `is_admin`, `sessions`, `invites`

**Files:**
- Modify: `src/reachstore/models.py`
- Create: `migrations/versions/0002_auth.py`
- Test: `tests/test_schema.py` (append)

**Interfaces:**
- Consumes: nothing
- Produces:
  - `User.is_admin: Mapped[bool]`
  - `UserSession` model → table `sessions`: `id`, `user_id`, `token_hash`, `created_at`, `expires_at`
  - `Invite` model → table `invites`: `id`, `email`, `display_name`, `is_admin`, `token_hash`, `created_at`, `expires_at`, `consumed_at`

**The model is named `UserSession`, not `Session`.** `models.py` and nearly every module that imports it also import `sqlalchemy.orm.Session`. Two different `Session` names in one file is a trap, and the table name stays `sessions`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_schema.py`:

```python
def test_auth_tables_exist_with_expected_columns(session):
    from sqlalchemy import inspect

    insp = inspect(session.get_bind())
    assert "sessions" in insp.get_table_names()
    assert "invites" in insp.get_table_names()

    session_cols = {c["name"] for c in insp.get_columns("sessions")}
    assert session_cols == {"id", "user_id", "token_hash", "created_at", "expires_at"}

    invite_cols = {c["name"] for c in insp.get_columns("invites")}
    assert invite_cols == {
        "id", "email", "display_name", "is_admin",
        "token_hash", "created_at", "expires_at", "consumed_at",
    }

    user_cols = {c["name"] for c in insp.get_columns("users")}
    assert "is_admin" in user_cols


def test_session_token_hash_is_unique(session):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy.exc import IntegrityError

    from reachstore.models import User, UserSession

    now = datetime(2026, 9, 18, tzinfo=UTC)
    user = User(email="dup@example.test", display_name="Dup", created_at=now)
    session.add(user)
    session.flush()

    for _ in range(2):
        session.add(
            UserSession(
                user_id=user.id,
                token_hash="a" * 64,
                created_at=now,
                expires_at=now + timedelta(days=30),
            )
        )
    with pytest.raises(IntegrityError):
        session.flush()


def test_deleting_a_user_deletes_their_sessions(session):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, select

    from reachstore.models import User, UserSession

    now = datetime(2026, 9, 18, tzinfo=UTC)
    user = User(email="cascade@example.test", display_name="Cascade", created_at=now)
    session.add(user)
    session.flush()
    session.add(
        UserSession(
            user_id=user.id,
            token_hash="b" * 64,
            created_at=now,
            expires_at=now + timedelta(days=30),
        )
    )
    session.flush()

    session.delete(user)
    session.flush()
    remaining = session.execute(select(func.count(UserSession.id))).scalar()
    assert remaining == 0
```

If `pytest` is not already imported at the top of `tests/test_schema.py`, add it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_schema.py -k "auth_tables or token_hash or cascade" -v`
Expected: FAIL — `sessions` is not in the table list, and `ImportError` on `UserSession`.

- [ ] **Step 3: Add the models**

In `src/reachstore/models.py`, add to `class User`, after `password_hash`:

```python
    is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
```

`server_default` matters as much as `default`: the Python default only applies to rows this code creates, while the server default is what makes the existing row valid when the migration adds a `NOT NULL` column. Declaring both here also keeps the model and the migration in agreement, so `alembic revision --autogenerate` will not later propose dropping one.

Then add two models at the end of the file:

```python
class UserSession(Base):
    """A logged-in browser session.

    Named `UserSession` rather than `Session` because almost every module that
    imports this one also imports `sqlalchemy.orm.Session`; the table itself is
    still `sessions`.

    `token_hash` holds the SHA-256 of the cookie value, never the value. A
    database dump therefore yields no usable sessions -- the same reasoning
    that applies to passwords.
    """

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Invite(Base):
    """A one-time invitation to create an account.

    Deliberately a separate table rather than fields on `users`: a `users` row
    then always denotes a usable account, instead of every query having to
    remember "...unless it is a pending one". `email` is not unique -- issuing
    a second invite for the same address is a new row.
    """

    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(120))
    is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

Every name in those models — `BigInteger`, `Boolean`, `DateTime`, `ForeignKey`, `String`, `text`, `Mapped`, `mapped_column`, `datetime` — is already imported at the top of `models.py`. Add no imports.

- [ ] **Step 4: Write the migration**

Create `migrations/versions/0002_auth.py`:

```python
"""auth: users.is_admin, sessions, invites

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "invites",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("is_admin", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("invites")
    op.drop_table("sessions")
    op.drop_column("users", "is_admin")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_schema.py -v`
Expected: PASS. The `engine` fixture runs `alembic upgrade head` against the test database, so the new migration is picked up automatically.

- [ ] **Step 6: Apply the migration to the development database**

```bash
export $(grep -E '^DATABASE_URL=' .env | xargs)
.venv/bin/alembic upgrade head
.venv/bin/alembic current
```

Expected: `current` reports `0002 (head)`.

**The `export` is required, not optional.** `migrations/env.py:15` reads
`os.environ.get("ALEMBIC_DATABASE_URL") or os.environ["DATABASE_URL"]` — it
does *not* read `.env`. Pydantic `Settings` loads `.env`, which is why the CLI
and the API work without this, but Alembic is invoked directly and does not go
through `Settings`. A bare `alembic upgrade head` fails with
`KeyError: 'DATABASE_URL'`. This is the database the web UI and CLI actually use; the test database is separate.

- [ ] **Step 7: Verify the existing row survived**

```bash
.venv/bin/python -c "
from sqlalchemy import select
from reachstore.config import get_settings
from reachstore.db import make_engine, make_session_factory
from reachstore.models import User
s = make_session_factory(make_engine(get_settings().database_url))()
for u in s.execute(select(User)).scalars():
    print(u.id, u.email, 'is_admin =', u.is_admin, '| empty password =', u.password_hash == '')
s.close()"
```

Expected: the one pre-existing row, `hand-verify@example.com`, with `is_admin = False` and an empty password. That row must remain unable to log in — Task 2's `verify_password` is what guarantees it.

- [ ] **Step 8: Run the full suite and commit**

```bash
.venv/bin/pytest
git add src/reachstore/models.py migrations/versions/0002_auth.py tests/test_schema.py
git commit -m "feat: schema for auth — users.is_admin, sessions, invites"
```

---

### Task 2: `api/auth.py` — passwords, sessions, invites

**Files:**
- Create: `src/reachstore/api/auth.py`
- Test: `tests/test_auth_unit.py`

**Interfaces:**
- Consumes: `UserSession`, `Invite`, `User` (Task 1); `deps.get_session`
- Produces:
  ```python
  COOKIE_NAME = "reachstore_session"
  SESSION_LIFETIME = timedelta(days=30)
  INVITE_LIFETIME = timedelta(days=7)
  MIN_PASSWORD_LENGTH = 8

  hash_password(password: str) -> str
  verify_password(password: str, encoded: str) -> bool
  spend_dummy_verify() -> None
  create_session(session, *, user_id: int, now: datetime) -> str      # returns raw token
  lookup_session(session, *, token: str, now: datetime) -> User | None
  delete_session(session, *, token: str) -> None
  delete_all_sessions(session, *, user_id: int) -> int
  create_invite(session, *, email, display_name, is_admin, now) -> str  # returns raw token
  consume_invite(session, *, token: str, now: datetime) -> Invite | None
  get_current_user(...) -> User          # FastAPI dependency, 401
  require_admin(...) -> User             # FastAPI dependency, 403
  ```

No endpoints in this task. Pure functions and dependencies, tested directly — so a failure here is unambiguous rather than tangled with HTTP.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_auth_unit.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest

from reachstore.api import auth
from reachstore.models import Invite, User, UserSession

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


def make_user(session, *, email="a@example.test", is_admin=False, password=None):
    user = User(
        email=email,
        display_name="A",
        password_hash=auth.hash_password(password) if password else "",
        is_admin=is_admin,
        created_at=NOW,
    )
    session.add(user)
    session.flush()
    return user


# --- passwords ---------------------------------------------------------------

def test_password_round_trip():
    encoded = auth.hash_password("correct horse battery staple")
    assert auth.verify_password("correct horse battery staple", encoded)


def test_wrong_password_rejected():
    encoded = auth.hash_password("right")
    assert not auth.verify_password("wrong", encoded)


def test_same_password_hashes_differently_each_time():
    """A per-password random salt means two identical passwords do not collide,
    so a stolen dump cannot be attacked by grouping equal hashes."""
    a = auth.hash_password("same")
    b = auth.hash_password("same")
    assert a != b
    assert auth.verify_password("same", a)
    assert auth.verify_password("same", b)


@pytest.mark.parametrize(
    "encoded",
    [
        "",                      # the pre-existing hand-verify row
        "not-a-hash",
        "scrypt$only$three$parts",
        "bcrypt$1$2$3$4$5",      # wrong scheme
        "scrypt$x$8$1$AAAA$BBBB",  # non-numeric cost parameter
    ],
)
def test_malformed_or_empty_hash_is_rejected_without_raising(encoded):
    """`users.password_hash` defaults to "" and one such row already exists.
    Returning False here is what makes it unable to authenticate -- no
    migration special case, no condition spread across queries."""
    assert auth.verify_password("anything", encoded) is False


def test_tampered_digest_rejected():
    encoded = auth.hash_password("secret")
    scheme, n, r, p, salt, dk = encoded.split("$")
    flipped = ("A" if dk[0] != "A" else "B") + dk[1:]
    assert not auth.verify_password("secret", "$".join([scheme, n, r, p, salt, flipped]))


# --- sessions ----------------------------------------------------------------

def test_create_then_lookup_returns_the_user(session):
    user = make_user(session)
    token = auth.create_session(session, user_id=user.id, now=NOW)
    found = auth.lookup_session(session, token=token, now=NOW)
    assert found is not None and found.id == user.id


def test_raw_token_is_not_stored(session):
    """Only the digest is persisted, so a dump yields no usable sessions."""
    from sqlalchemy import select

    user = make_user(session)
    token = auth.create_session(session, user_id=user.id, now=NOW)
    stored = session.execute(select(UserSession.token_hash)).scalars().all()
    assert token not in stored
    assert len(stored[0]) == 64


def test_unknown_token_returns_none(session):
    assert auth.lookup_session(session, token="nope", now=NOW) is None


def test_expired_session_is_rejected_and_deleted(session):
    """Deleting on the way past means expiry needs no scheduler."""
    from sqlalchemy import func, select

    user = make_user(session)
    token = auth.create_session(session, user_id=user.id, now=NOW)
    later = NOW + auth.SESSION_LIFETIME + timedelta(seconds=1)

    assert auth.lookup_session(session, token=token, now=later) is None
    assert session.execute(select(func.count(UserSession.id))).scalar() == 0


def test_session_valid_right_up_to_expiry(session):
    user = make_user(session)
    token = auth.create_session(session, user_id=user.id, now=NOW)
    just_before = NOW + auth.SESSION_LIFETIME - timedelta(seconds=1)
    assert auth.lookup_session(session, token=token, now=just_before) is not None


def test_delete_session_logs_out(session):
    user = make_user(session)
    token = auth.create_session(session, user_id=user.id, now=NOW)
    auth.delete_session(session, token=token)
    assert auth.lookup_session(session, token=token, now=NOW) is None


def test_delete_session_is_idempotent(session):
    auth.delete_session(session, token="never-existed")
    auth.delete_session(session, token="never-existed")


def test_delete_all_sessions_revokes_every_one(session):
    user = make_user(session)
    other = make_user(session, email="b@example.test")
    tokens = [auth.create_session(session, user_id=user.id, now=NOW) for _ in range(3)]
    kept = auth.create_session(session, user_id=other.id, now=NOW)

    assert auth.delete_all_sessions(session, user_id=user.id) == 3
    for t in tokens:
        assert auth.lookup_session(session, token=t, now=NOW) is None
    assert auth.lookup_session(session, token=kept, now=NOW) is not None


# --- invites -----------------------------------------------------------------

def test_invite_round_trip(session):
    token = auth.create_invite(
        session, email="new@example.test", display_name="New", is_admin=True, now=NOW
    )
    invite = auth.consume_invite(session, token=token, now=NOW)
    assert invite is not None
    assert invite.email == "new@example.test"
    assert invite.display_name == "New"
    assert invite.is_admin is True
    assert invite.consumed_at == NOW


def test_invite_cannot_be_consumed_twice(session):
    token = auth.create_invite(
        session, email="once@example.test", display_name="Once", is_admin=False, now=NOW
    )
    assert auth.consume_invite(session, token=token, now=NOW) is not None
    assert auth.consume_invite(session, token=token, now=NOW) is None


def test_expired_invite_is_rejected(session):
    token = auth.create_invite(
        session, email="old@example.test", display_name="Old", is_admin=False, now=NOW
    )
    later = NOW + auth.INVITE_LIFETIME + timedelta(seconds=1)
    assert auth.consume_invite(session, token=token, now=later) is None


def test_unknown_invite_token_is_rejected(session):
    assert auth.consume_invite(session, token="nope", now=NOW) is None


def test_invite_raw_token_is_not_stored(session):
    from sqlalchemy import select

    token = auth.create_invite(
        session, email="h@example.test", display_name="H", is_admin=False, now=NOW
    )
    assert token not in session.execute(select(Invite.token_hash)).scalars().all()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_auth_unit.py -v`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'reachstore.api.auth'`.

- [ ] **Step 3: Write `src/reachstore/api/auth.py`**

```python
"""The boundary between a request and an identity.

This module is the only place a cookie becomes a `User`, and the only place
that writes SQL against `users`, `sessions`, or `invites`. Same discipline as
`query.visible_to` being the sole tenant predicate: one function to audit.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from reachstore.api.deps import get_session
from reachstore.models import Invite, User, UserSession

COOKIE_NAME = "reachstore_session"
SESSION_LIFETIME = timedelta(days=30)
INVITE_LIFETIME = timedelta(days=7)
MIN_PASSWORD_LENGTH = 8

# scrypt parameters. Measured at 41 ms on the development machine: slow enough
# that offline brute force is expensive, fast enough that a login feels
# instant. `maxmem` is derived from the stored parameters rather than fixed, so
# raising the cost later does not silently invalidate every existing password.
_N = 2**15
_R = 8
_P = 1
_DKLEN = 64


def _maxmem(n: int, r: int) -> int:
    return 128 * n * r * 2


def hash_password(password: str) -> str:
    """Encode as `scrypt$n$r$p$<b64 salt>$<b64 digest>`.

    The salt is random per password, so two identical passwords do not produce
    identical hashes and a stolen dump cannot be attacked by grouping equal
    rows.
    """
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=_N,
        r=_R,
        p=_P,
        maxmem=_maxmem(_N, _R),
        dklen=_DKLEN,
    )
    return "scrypt${}${}${}${}${}".format(
        _N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(dk).decode()
    )


def verify_password(password: str, encoded: str) -> bool:
    """False for anything that is not a valid matching hash. Never raises.

    `users.password_hash` defaults to "" and one such row already exists
    (`hand-verify@example.com`, left over from Plan 1 hand-verification).
    Returning False for an empty or malformed value is what makes such a row
    unable to authenticate -- without a migration special case, and without a
    condition that has to be remembered at every query.
    """
    # Only PARSING is guarded. hashlib.scrypt is deliberately outside the try:
    # it raises ValueError for bad or over-budget parameters, and swallowing
    # that would turn a wrong _maxmem into a total authentication outage that
    # presents as "wrong password" -- no exception, no log, no failing test.
    # Fail loudly on a crypto fault; fail False on malformed input.
    try:
        scheme, n, r, p, salt_b64, dk_b64 = encoded.split("$")
        if scheme != "scrypt":
            return False
        n_i, r_i, p_i = int(n), int(r), int(p)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
    except (AttributeError, ValueError, TypeError):
        return False

    dk = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=n_i,
        r=r_i,
        p=p_i,
        maxmem=_maxmem(n_i, r_i),
        dklen=len(expected),
    )
    return secrets.compare_digest(dk, expected)


_DUMMY: str | None = None


def spend_dummy_verify() -> None:
    """Burn the same CPU a real verification would.

    Called on the unknown-email branch of login. Without it, an unknown
    address returns measurably faster than a known one with a wrong password,
    which turns response latency into a user-enumeration oracle.
    """
    global _DUMMY
    if _DUMMY is None:
        # Populating it already cost one scrypt; returning here keeps the
        # first unknown-email request from costing two, in the one function
        # whose entire purpose is to equalise timing.
        _DUMMY = hash_password(secrets.token_urlsafe(16))
        return
    verify_password("x", _DUMMY)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(session: Session, *, user_id: int, now: datetime) -> str:
    """Issue a session and return the RAW token -- the only time it exists.

    Only its SHA-256 digest is stored, so a database dump contains no usable
    sessions.
    """
    token = secrets.token_urlsafe(32)
    session.add(
        UserSession(
            user_id=user_id,
            token_hash=_digest(token),
            created_at=now,
            expires_at=now + SESSION_LIFETIME,
        )
    )
    session.flush()
    return token


def lookup_session(session: Session, *, token: str, now: datetime) -> User | None:
    """The user for this token, or None. Deletes the row if it has expired."""
    row = (
        session.execute(
            select(UserSession).where(UserSession.token_hash == _digest(token))
        )
        .scalars()
        .one_or_none()
    )
    if row is None:
        return None
    if row.expires_at <= now:
        # Left in place rather than deleted. This function runs on every
        # authenticated request via get_current_user, and `get_session` never
        # commits -- it yields and then closes, which rolls back -- so a delete
        # here would be discarded anyway on the read-only path. Committing
        # instead would be worse: it would also commit whatever unrelated work
        # is pending in the request-scoped session, and a GET should not write.
        # An expired row is inert because this check re-runs on every lookup;
        # reclaiming the rows is a separate concern if it ever matters.
        return None
    return session.get(User, row.user_id)


def delete_session(session: Session, *, token: str) -> None:
    session.execute(delete(UserSession).where(UserSession.token_hash == _digest(token)))


def delete_all_sessions(session: Session, *, user_id: int) -> int:
    """Revoke every session for one user. Returns how many were removed."""
    result = session.execute(delete(UserSession).where(UserSession.user_id == user_id))
    return result.rowcount or 0


def create_invite(
    session: Session, *, email: str, display_name: str, is_admin: bool, now: datetime
) -> str:
    """Issue an invite and return the RAW token -- the only time it exists."""
    token = secrets.token_urlsafe(32)
    session.add(
        Invite(
            email=email,
            display_name=display_name,
            is_admin=is_admin,
            token_hash=_digest(token),
            created_at=now,
            expires_at=now + INVITE_LIFETIME,
        )
    )
    session.flush()
    return token


def consume_invite(session: Session, *, token: str, now: datetime) -> Invite | None:
    """Mark an invite spent and return it, or None if unusable."""
    row = (
        session.execute(select(Invite).where(Invite.token_hash == _digest(token)))
        .scalars()
        .one_or_none()
    )
    if row is None or row.consumed_at is not None or row.expires_at <= now:
        return None
    row.consumed_at = now
    session.flush()
    return row


def get_current_user(
    session: Session = Depends(get_session),
    reachstore_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> User:
    """The authenticated user, or 401.

    `alias=COOKIE_NAME` rather than relying on the parameter being spelled to
    match: a FastAPI Cookie parameter whose name differs from the cookie reads
    None *silently*, with no error, which would disable authentication rather
    than break it loudly.
    """
    if reachstore_session is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    user = lookup_session(session, token=reachstore_session, now=datetime.now(UTC))
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="admin only")
    return user
```

`datetime.now(UTC)` appears only inside `get_current_user`, which is part of the `api/` entrypoint package. Every other function takes `now` as a parameter, which is what makes the expiry boundary testable to the second rather than by sleeping.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_auth_unit.py -v`
Expected: PASS — 22 test items (18 functions, one of which is parametrised 5 ways).

- [ ] **Step 5: Confirm the constraint boundary**

```bash
grep -n "select(\|delete(" src/reachstore/api/auth.py
```

Every hit must reference `UserSession`, `Invite`, or `User` — never `Item`, `Source`, or `FetchRun`. Paste the output into your report.

- [ ] **Step 6: Run the full suite and commit**

```bash
.venv/bin/pytest
git add src/reachstore/api/auth.py tests/test_auth_unit.py
git commit -m "feat: auth module — scrypt passwords, revocable sessions, invites"
```

---

### Task 3: Authenticated test fixtures, and retrofit the 18 existing API tests

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/test_api_read.py` (7 tests), `tests/test_api_sources.py` (4), `tests/test_api_collect.py` (7)

**Interfaces:**
- Consumes: `auth.hash_password`, `auth.create_session`, `auth.COOKIE_NAME` (Task 2)
- Produces: fixtures `make_user`, `client_for`, `admin_client`, `user_client`, `anon_client`, and an autouse reset of `collect_runner._running`

**This task changes no production code and must leave the suite green.** That is the whole point of its position in the order: the endpoints do not require authentication yet, so a client that carries a cookie behaves exactly like one that does not. Task 5 then adds the requirement and these same tests keep passing.

**The trap to avoid:** a session's validity is checked against `datetime.now(UTC)` inside `get_current_user`, so **the fixture must create sessions with the real clock**, not a fixed date. A session stamped `2026-09-18` would already be expired by the time anyone runs the suite later.

- [ ] **Step 1: Add the fixtures to `tests/conftest.py`**

Add these imports at the top:

```python
import itertools
from datetime import UTC, datetime
```

Then append:

```python
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
```

- [ ] **Step 2: Retrofit `tests/test_api_sources.py`**

Delete its local `make_client` helper. Replace each `make_client(session)` call with the `admin_client` fixture, taken as a test parameter. For example:

```python
def test_sources_endpoint_returns_every_source(session, admin_client):
    session.add(
        Source(kind="rss", identifier="https://a/feed", tier=1, config_json={}, created_at=NOW)
    )
    session.flush()

    body = admin_client.get("/api/sources").json()
    assert [s["identifier"] for s in body["sources"]] == ["https://a/feed"]
```

The two `SourceStatusOut` construction tests do not use a client at all and need no change.

**Change only which client the test uses. Do not weaken or delete an assertion.** A diff that alters an assertion rather than the client is a review finding.

- [ ] **Step 3: Retrofit `tests/test_api_read.py`**

Same treatment: delete the local `make_client`, take `user_client` as a parameter, and call it instead. These are read endpoints, so a non-admin is the right client — and using `user_client` here is what will prove in Task 5 that reads are *not* admin-gated.

- [ ] **Step 4: Retrofit `tests/test_api_collect.py`**

Same treatment with `admin_client`, since `POST /api/collect` becomes admin-only. Delete its local autouse `_running` reset — conftest now provides it for the whole suite.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest`
Expected: PASS — 141 items (116 existing, 22 from Task 2, 3 from Task 1), zero warnings. **No test count should drop.** A drop means a test was deleted rather than retrofitted.

- [ ] **Step 6: Commit**

```bash
git add tests/
git commit -m "test: authenticated client fixtures, adopted by the existing API tests"
```

---

### Task 4: Login, logout, and me

**Files:**
- Modify: `src/reachstore/api/schemas.py`, `src/reachstore/api/routes.py`
- Test: `tests/test_api_auth.py`

**Interfaces:**
- Consumes: `auth.*` (Task 2); fixtures from Task 3
- Produces: `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`; schemas `LoginRequest`, `UserOut`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_auth.py`:

```python
from reachstore.api.auth import COOKIE_NAME


def test_login_sets_a_cookie_and_returns_the_user(anon_client, make_user):
    user, password = make_user(email="alice@example.test")

    response = anon_client.post(
        "/api/auth/login", json={"email": "alice@example.test", "password": password}
    )
    assert response.status_code == 200
    assert response.json()["email"] == "alice@example.test"
    assert response.json()["is_admin"] is False
    assert COOKIE_NAME in response.cookies


def test_login_then_me_returns_the_same_user(anon_client, make_user):
    _user, password = make_user(email="bob@example.test")
    anon_client.post(
        "/api/auth/login", json={"email": "bob@example.test", "password": password}
    )
    me = anon_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "bob@example.test"


def test_me_without_a_session_is_401(anon_client):
    assert anon_client.get("/api/auth/me").status_code == 401


def test_wrong_password_and_unknown_email_are_indistinguishable(anon_client, make_user):
    """Identical status and body for both, so the response cannot be used to
    discover which addresses have accounts."""
    make_user(email="real@example.test", password="the-real-password")

    wrong = anon_client.post(
        "/api/auth/login", json={"email": "real@example.test", "password": "nope"}
    )
    unknown = anon_client.post(
        "/api/auth/login", json={"email": "ghost@example.test", "password": "nope"}
    )

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_login_rejects_the_empty_password_hash(anon_client, session):
    """The pre-existing hand-verify row has password_hash == "". It must not be
    loggable-in with an empty password, or with anything else."""
    from datetime import UTC, datetime

    from reachstore.models import User

    session.add(
        User(
            email="legacy@example.test",
            display_name="Legacy",
            password_hash="",
            created_at=datetime(2026, 9, 18, tzinfo=UTC),
        )
    )
    session.flush()

    for attempt in ("", "anything"):
        response = anon_client.post(
            "/api/auth/login", json={"email": "legacy@example.test", "password": attempt}
        )
        assert response.status_code == 401


def test_logout_invalidates_the_session(client_for):
    client, _user, _pw = client_for()
    assert client.get("/api/auth/me").status_code == 200

    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_logout_without_a_session_is_401(anon_client):
    assert anon_client.post("/api/auth/logout").status_code == 401


def test_admin_flag_is_reported(client_for):
    client, _user, _pw = client_for(is_admin=True)
    assert client.get("/api/auth/me").json()["is_admin"] is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_api_auth.py -v`
Expected: FAIL — 404 on `/api/auth/login`; the routes do not exist.

- [ ] **Step 3: Add the schemas**

Append to `src/reachstore/api/schemas.py`:

```python
class LoginRequest(BaseModel):
    email: str
    password: str


class SetupRequest(BaseModel):
    token: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str
    is_admin: bool
```

`SetupRequest` is added now, alongside its sibling, and used in Task 7.

- [ ] **Step 4: Add the routes**

In `src/reachstore/api/routes.py`, add to the imports:

```python
from datetime import UTC, datetime

from reachstore.api.auth import (
    COOKIE_NAME,
    SESSION_LIFETIME,
    create_session,
    delete_session,
    get_current_user,
    spend_dummy_verify,
    verify_password,
)
from reachstore.api.schemas import LoginRequest, UserOut
from reachstore.models import User
```

`Item` is already imported from `reachstore.models`; extend that line rather than adding a second import from the same module.

Then append:

```python
def _set_session_cookie(response: Response, token: str) -> None:
    """One place that writes the cookie, so login and setup cannot drift.

    `secure` is deliberately absent: there is no HTTPS on localhost and
    setting it would stop the cookie being sent at all. See section 9 of the
    spec -- this is a decision, not an oversight.
    """
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,
        samesite="lax",
        path="/",
    )


@router.post("/auth/login", response_model=UserOut)
def post_login(
    body: LoginRequest, response: Response, session: Session = Depends(get_session)
) -> UserOut:
    """401 with one identical body for a wrong password and an unknown email.

    The unknown-email branch still spends a full password verification, so the
    two cases take comparable time. Without that, latency alone reveals which
    addresses have accounts.
    """
    user = (
        session.execute(select(User).where(User.email == body.email))
        .scalars()
        .one_or_none()
    )
    if user is None:
        spend_dummy_verify()
        raise HTTPException(status_code=401, detail="invalid email or password")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid email or password")

    token = create_session(session, user_id=user.id, now=datetime.now(UTC))
    session.commit()
    _set_session_cookie(response, token)
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
    )


@router.post("/auth/logout")
def post_logout(
    response: Response,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    reachstore_session: str | None = Cookie(default=None),
) -> dict[str, bool]:
    if reachstore_session is not None:
        delete_session(session, token=reachstore_session)
        session.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/auth/me", response_model=UserOut)
def get_me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
    )
```

Add `Cookie` to the `fastapi` import line and `select` to a new `from sqlalchemy import select` import.

**This is the one deliberate exception to "routes.py builds no SQL":** the single `select(User).where(User.email == ...)` in `post_login`. Everything else still goes through `auth.py` or `query.py`. If a reviewer prefers, moving it to an `auth.find_user_by_email` helper is a strictly better shape — note it in your report either way.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_api_auth.py -v`
Expected: PASS (8 tests).

- [ ] **Step 6: Run the full suite and commit**

```bash
.venv/bin/pytest
git add src/reachstore/api tests/test_api_auth.py
git commit -m "feat: login, logout, and me endpoints"
```

---

### Task 5: Require authentication on every existing endpoint

**Files:**
- Modify: `src/reachstore/api/routes.py`, `src/reachstore/api/deps.py`
- Test: `tests/test_api_permissions.py`, `tests/test_api_tenant_http.py`

**Interfaces:**
- Consumes: `auth.get_current_user`, `auth.require_admin` (Task 2); the Task 3 fixtures
- Produces: `DEFAULT_USER_ID` no longer exists. Every route takes an authenticated `User`.

This is where `DEFAULT_USER_ID` dies. Plan 2's deps.py docstring predicted exactly this: *"Plan 2 replaces a constant instead of threading a new parameter through every call site."* Three call sites change.

Access levels, from the spec's §7:

| Endpoint | Anonymous | User | Admin |
|---|---|---|---|
| `POST /api/auth/login` | 200/401 | 200 | 200 |
| `POST /api/auth/setup` | 200/400 | 200/400 | 200/400 |
| `GET /api/auth/me` | 401 | 200 | 200 |
| `POST /api/auth/logout` | 401 | 200 | 200 |
| `GET /api/feed` | 401 | 200 | 200 |
| `GET /api/search` | 401 | 200 | 200 |
| `GET /api/items/{id}` | 401 | 200/404 | 200/404 |
| `GET /api/catalog` | 401 | 200 | 200 |
| `PUT /api/subscriptions/{id}` | 401 | 204 | 204 |
| `DELETE /api/subscriptions/{id}` | 401 | 204 | 204 |
| `GET /api/sources` | 401 | **403** | 200 |
| `POST /api/collect` | 401 | **403** | 202 |

The last two rows are the whole point of the admin flag: diagnostics and control are operator surface. The catalog row exists because a non-admin still has to see sources in order to subscribe to them — `ItemSummary.source_identifier` is already rendered in every feed row (`web/src/components/ItemList.jsx`), so identifiers were never secret to a logged-in user. What is operator-only is the *health and control*, not the identifier.

- [ ] **Step 1: Write the failing permission matrix**

Create `tests/test_api_permissions.py`:

```python
"""One table, three clients. A new endpoint added without a row here is the
failure this file exists to catch."""

import pytest

# (method, path, anonymous, non-admin, admin)
CASES = [
    ("GET", "/api/feed", 401, 200, 200),
    ("GET", "/api/search?q=anything", 401, 200, 200),
    ("GET", "/api/items/999999", 401, 404, 404),
    ("GET", "/api/sources", 401, 403, 200),
    ("GET", "/api/auth/me", 401, 200, 200),
    ("POST", "/api/auth/logout", 401, 200, 200),
]


@pytest.fixture
def no_op_collect(monkeypatch):
    """POST /api/collect returns 202 and schedules real work. The matrix cares
    only about the status code, so the background task is stubbed out -- the
    suite must make no network calls."""
    from reachstore.api import collect_runner

    monkeypatch.setattr(collect_runner, "run_collection", lambda tier, force: None)


@pytest.mark.parametrize(("method", "path", "anon", "user", "admin"), CASES)
def test_permission_matrix(method, path, anon, user, admin, anon_client, user_client, admin_client):
    for client, expected in ((anon_client, anon), (user_client, user), (admin_client, admin)):
        response = client.request(method, path)
        assert response.status_code == expected, (
            f"{method} {path} as {client}: expected {expected}, got {response.status_code}"
        )


def test_collect_is_admin_only(anon_client, user_client, admin_client, no_op_collect):
    body = {"tier": 1}
    assert anon_client.post("/api/collect", json=body).status_code == 401
    assert user_client.post("/api/collect", json=body).status_code == 403
    assert admin_client.post("/api/collect", json=body).status_code == 202


def test_an_unknown_cookie_is_401_not_500(session):
    """A cookie left over from a revoked or deleted session must read as
    'not logged in', not as a crash."""
    from fastapi.testclient import TestClient

    from reachstore.api.app import create_app
    from reachstore.api.auth import COOKIE_NAME
    from reachstore.api.deps import get_session

    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)
    client.cookies.set(COOKIE_NAME, "this-token-was-never-issued")

    assert client.get("/api/feed").status_code == 401


def test_default_user_id_is_gone():
    """The constant existed only to keep the tenant path live before there were
    users. A surviving import would mean a route is still hard-coded to user 1."""
    from reachstore.api import deps

    assert not hasattr(deps, "DEFAULT_USER_ID")
```

Note: `test_permission_matrix` iterates three clients inside one test, so each of the three fixtures builds a user. That is intentional — it keeps the table to one row per endpoint.

- [ ] **Step 2: Write the failing tenant-isolation test**

Create `tests/test_api_tenant_http.py`:

```python
"""Tenant isolation asserted through HTTP, not just through query.visible_to.

Before this task the API had one hard-coded user, so `owner_user_id` could
only ever be tested at the query layer. Now that a request carries a real
identity, the isolation is provable end to end.
"""

from datetime import UTC, datetime

from reachstore.adapters.base import NormalizedItem
from reachstore.models import Source
from reachstore.store import upsert_items

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


def _source(session):
    source = Source(
        kind="rss", identifier="https://t/feed", tier=1, config_json={}, created_at=NOW
    )
    session.add(source)
    session.flush()
    return source


def _item(session, source, *, external_id, owner_user_id, raw_dir):
    upsert_items(
        session,
        source_id=source.id,
        items=[
            NormalizedItem(
                external_id=external_id,
                url=f"https://t/{external_id}",
                title=external_id,
                content_text="shared vocabulary term",
                published_at=NOW,
            )
        ],
        owner_user_id=owner_user_id,
        raw_dir=raw_dir,
        now=NOW,
    )


def test_private_items_are_invisible_to_other_users(session, client_for, raw_dir):
    alice_client, alice, _ = client_for()
    bob_client, bob, _ = client_for()
    source = _source(session)

    _item(session, source, external_id="public", owner_user_id=None, raw_dir=raw_dir)
    _item(session, source, external_id="alices", owner_user_id=alice.id, raw_dir=raw_dir)
    _item(session, source, external_id="bobs", owner_user_id=bob.id, raw_dir=raw_dir)
    session.flush()

    alice_titles = {i["title"] for i in alice_client.get("/api/feed").json()["items"]}
    bob_titles = {i["title"] for i in bob_client.get("/api/feed").json()["items"]}

    assert alice_titles == {"public", "alices"}
    assert bob_titles == {"public", "bobs"}


def test_another_users_item_is_404_not_403(session, client_for, raw_dir):
    """Indistinguishable from a nonexistent id, so the endpoint cannot be used
    to probe for the existence of someone else's private items."""
    alice_client, alice, _ = client_for()
    bob_client, _bob, _ = client_for()
    source = _source(session)

    _item(session, source, external_id="alices", owner_user_id=alice.id, raw_dir=raw_dir)
    session.flush()

    item_id = alice_client.get("/api/feed").json()["items"][0]["id"]
    assert alice_client.get(f"/api/items/{item_id}").status_code == 200
    assert bob_client.get(f"/api/items/{item_id}").status_code == 404
    assert bob_client.get("/api/items/999999").status_code == 404


def test_search_is_also_isolated(session, client_for, raw_dir):
    alice_client, alice, _ = client_for()
    bob_client, _bob, _ = client_for()
    source = _source(session)

    _item(session, source, external_id="alices", owner_user_id=alice.id, raw_dir=raw_dir)
    session.flush()

    assert len(alice_client.get("/api/search?q=vocabulary").json()["items"]) == 1
    assert bob_client.get("/api/search?q=vocabulary").json()["items"] == []
```

- [ ] **Step 3: Run both files to verify they fail**

Run: `.venv/bin/pytest tests/test_api_permissions.py tests/test_api_tenant_http.py -v`
Expected: FAIL — every endpoint currently returns 200 for an anonymous client, `deps.DEFAULT_USER_ID` still exists, and every user sees every item because the routes all pass user 1.

- [ ] **Step 4: Apply the dependencies**

In `src/reachstore/api/routes.py`:

Change the deps import to drop the constant:

```python
from reachstore.api.deps import get_session
```

Add `require_admin` to the existing `reachstore.api.auth` import (it already brings in `get_current_user` from Task 4).

Then, endpoint by endpoint:

```python
@router.get("/sources", response_model=SourcesResponse)
def list_sources(
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> SourcesResponse:
```

```python
def post_collect(
    body: CollectRequest,
    background: BackgroundTasks,
    response: Response,
    _admin: User = Depends(require_admin),
) -> CollectResponse:
```

```python
def get_feed(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=query.MAX_LIMIT),
    before_published_at: AwareDatetime | None = None,
    before_id: int | None = None,
) -> FeedResponse:
```

```python
def get_search(
    q: str = Query(..., min_length=1),
    kind: str | None = None,
    limit: int = Query(50, ge=1, le=query.MAX_LIMIT),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SearchResponse:
```

```python
def get_one_item(
    item_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ItemDetail:
```

Then replace all three `user_id=DEFAULT_USER_ID` with `user_id=user.id`.

The two admin-only handlers name their dependency `_admin` because they never read the user — the leading underscore says the parameter exists for its side effect. `require_admin` still runs and still raises; a dependency is not skipped for being unused.

- [ ] **Step 5: Delete the constant**

In `src/reachstore/api/deps.py`, delete `DEFAULT_USER_ID = 1` and its whole docstring (lines 13-21).

Also update `get_one_item`'s docstring in `routes.py` — it currently says "once Plan 2 introduces real users", which has now happened:

```python
    """404 both when the item does not exist and when it is not visible.

    The two are deliberately indistinguishable, so this endpoint cannot be
    used to probe for the existence of another user's private items.
    """
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_api_permissions.py tests/test_api_tenant_http.py -v`
Expected: PASS.

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/pytest`
Expected: PASS. **The 18 tests retrofitted in Task 3 must still pass without further edits** — they already carry cookies. If any of them now fails, the Task 3 retrofit picked the wrong client for that test (a read test on `admin_client` would still pass, but a `/api/sources` test on `user_client` would now 403). Fix the client choice, not the assertion.

- [ ] **Step 8: Confirm the constant is gone everywhere**

```bash
grep -rn "DEFAULT_USER_ID" src/ tests/ web/src/ || echo "clean"
```

Expected: exactly one hit — the `test_default_user_id_is_gone` assertion in `tests/test_api_permissions.py`. **No hit in `src/`.**

**Do not grep all of `docs/`, and do not edit anything under `docs/superpowers/specs/`, `docs/superpowers/plans/`, or `docs/superpowers/reviews/` other than this plan.** Those are the immutable historical record of earlier work — Plan 1's spec, plan, and per-task review reports legitimately describe `DEFAULT_USER_ID` as a thing that existed at that time, and rewriting them would falsify the decision record. The only living document that needs updating is `docs/architecture.md`, and that is Task 12's job, not yours.

- [ ] **Step 9: Commit**

```bash
git add src/reachstore/api tests/
git commit -m "feat: require authentication on every endpoint; remove DEFAULT_USER_ID"
```

---

### Task 6: CLI — invite, set-password, revoke-sessions

**Files:**
- Modify: `src/reachstore/cli.py`, `src/reachstore/config.py`, `.env.example`
- Test: `tests/test_cli_auth.py`

**Interfaces:**
- Consumes: `auth.create_invite`, `auth.hash_password`, `auth.delete_all_sessions` (Task 2)
- Produces: three Typer commands; `Settings.web_base_url`

There is no signup endpoint, and no first-run bootstrap screen. An account starts with someone who already has shell access to this machine running a command. That is the whole access-control story for a localhost tool, and it is why no HTTP endpoint can create an account from nothing.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_auth.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_cli_auth.py -v`
Expected: FAIL — `No such command 'invite'`, exit code 2.

- [ ] **Step 3: Add the `web_base_url` setting**

In `src/reachstore/config.py`, add to `Settings`:

```python
    web_base_url: str = "http://127.0.0.1:5173"
```

And add a line to `.env.example`:

```
# Base URL the invite command builds setup links against. The Vite dev server
# is 5173; when FastAPI serves the built frontend it is 8000.
WEB_BASE_URL=http://127.0.0.1:5173
```

Hardcoding 5173 in the invite output would print a broken link in production, where FastAPI serves `web/dist` on 8000. One setting, two deployments.

- [ ] **Step 4: Add the CLI commands**

In `src/reachstore/cli.py`, adjust the imports. Its current block was read to confirm each point:

- `from datetime import UTC, datetime` is **already present** — do not add it again.
- `get_settings` is **already imported** from `reachstore.config`.
- There is **no** `from sqlalchemy import ...` line. Add `from sqlalchemy import select`.
- It imports `from reachstore.models import Source`. Extend that line to `from reachstore.models import Source, User`.
- Add the auth import:

```python
from reachstore.api.auth import (
    MIN_PASSWORD_LENGTH,
    create_invite,
    delete_all_sessions,
    hash_password,
)
```

Append the three commands:

```python
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
    session = _session()
    try:
        existing = (
            session.execute(select(User).where(User.email == email))
            .scalars()
            .one_or_none()
        )
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
        user = (
            session.execute(select(User).where(User.email == email))
            .scalars()
            .one_or_none()
        )
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
        user = (
            session.execute(select(User).where(User.email == email))
            .scalars()
            .one_or_none()
        )
        if user is None:
            typer.echo(f"No account for {email}.")
            raise typer.Exit(code=1)
        count = delete_all_sessions(session, user_id=user.id)
        session.commit()
        typer.echo(f"Revoked {count} session(s) for {email}.")
    finally:
        session.close()
```

`get_settings` is already imported in `cli.py`. `select(User)` here is the CLI's own read against a table `auth.py` owns — see the ledger note in the constraints; if you prefer, adding `auth.find_user_by_email(session, email)` and using it in all four places (three here plus `post_login`) is a cleaner shape. Either is acceptable; say which you chose in your report.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_cli_auth.py -v`
Expected: PASS (8 tests).

- [ ] **Step 6: Create a real admin account by hand**

This account is what you will log in with from Task 9 onward, so create it now against the development database:

```bash
.venv/bin/python -m reachstore.cli invite you@example.com --name "You" --admin
```

Copy the printed URL somewhere — you need it in Task 7 to verify the setup flow, and the link works exactly once. The token is the part after `#setup=`.

- [ ] **Step 7: Run the full suite and commit**

```bash
.venv/bin/pytest
git add src/reachstore tests/test_cli_auth.py .env.example
git commit -m "feat: invite, set-password, and revoke-sessions CLI commands"
```

---

### Task 7: `POST /api/auth/setup` — redeem an invite

**Files:**
- Modify: `src/reachstore/api/routes.py`
- Test: `tests/test_api_auth.py` (append)

**Interfaces:**
- Consumes: `auth.consume_invite`, `auth.hash_password`, `auth.MIN_PASSWORD_LENGTH`, `_set_session_cookie` (Tasks 2 and 4); `SetupRequest` (Task 4)
- Produces: `POST /api/auth/setup`

Deliberately unauthenticated — it is how a person who has no account gets one. Its access control is possession of a token that exists in exactly one place: the URL the operator handed over.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api_auth.py`:

```python
# --- setup -------------------------------------------------------------------

from datetime import UTC, datetime  # noqa: E402  (grouped with the setup tests)

from reachstore.api import auth  # noqa: E402


def _invite(session, *, email="invited@example.test", is_admin=False):
    return auth.create_invite(
        session,
        email=email,
        display_name="Invited",
        is_admin=is_admin,
        now=datetime.now(UTC),
    )


def test_setup_creates_the_account_and_logs_it_in(anon_client, session):
    token = _invite(session)

    response = anon_client.post(
        "/api/auth/setup", json={"token": token, "password": "a-good-password"}
    )
    assert response.status_code == 200
    assert response.json()["email"] == "invited@example.test"
    assert response.json()["display_name"] == "Invited"
    assert auth.COOKIE_NAME in response.cookies

    # Already logged in -- no second trip through login.
    assert anon_client.get("/api/auth/me").status_code == 200


def test_setup_carries_the_invited_admin_flag(anon_client, session):
    token = _invite(session, email="newboss@example.test", is_admin=True)
    body = anon_client.post(
        "/api/auth/setup", json={"token": token, "password": "a-good-password"}
    ).json()
    assert body["is_admin"] is True


def test_the_new_account_can_log_in_afterwards(anon_client, session):
    token = _invite(session, email="later@example.test")
    anon_client.post(
        "/api/auth/setup", json={"token": token, "password": "a-good-password"}
    )
    anon_client.post("/api/auth/logout")

    response = anon_client.post(
        "/api/auth/login",
        json={"email": "later@example.test", "password": "a-good-password"},
    )
    assert response.status_code == 200


def test_setup_token_works_exactly_once(anon_client, session):
    token = _invite(session, email="once@example.test")
    assert (
        anon_client.post(
            "/api/auth/setup", json={"token": token, "password": "a-good-password"}
        ).status_code
        == 200
    )
    second = anon_client.post(
        "/api/auth/setup", json={"token": token, "password": "another-password"}
    )
    assert second.status_code == 400


def test_setup_rejects_an_unknown_token(anon_client):
    response = anon_client.post(
        "/api/auth/setup", json={"token": "never-issued", "password": "a-good-password"}
    )
    assert response.status_code == 400


def test_setup_rejects_an_expired_invite(anon_client, session):
    """Stamped far enough in the past that the handler's real clock is past
    expiry, since the handler reads datetime.now(UTC) and cannot be injected."""
    from datetime import timedelta

    long_ago = datetime.now(UTC) - auth.INVITE_LIFETIME - timedelta(days=1)
    token = auth.create_invite(
        session,
        email="stale@example.test",
        display_name="Stale",
        is_admin=False,
        now=long_ago,
    )
    response = anon_client.post(
        "/api/auth/setup", json={"token": token, "password": "a-good-password"}
    )
    assert response.status_code == 400


def test_setup_rejects_a_short_password_without_consuming_the_invite(anon_client, session):
    """Validation must come before consumption, or a typo burns the link and
    the person has to ask the operator for a new one."""
    token = _invite(session, email="typo@example.test")

    assert (
        anon_client.post("/api/auth/setup", json={"token": token, "password": "abc"}).status_code
        == 400
    )
    assert (
        anon_client.post(
            "/api/auth/setup", json={"token": token, "password": "a-good-password"}
        ).status_code
        == 200
    )


def test_setup_is_409_when_the_email_already_has_an_account(anon_client, session, make_user):
    """An invite issued before the account existed must not be able to take it
    over. 409 rather than the uniform 400, per the spec: the holder of the
    token already knows the email it names, so saying "that account exists"
    leaks nothing they did not supply, and it is the one failure a person can
    actually act on.
    """
    make_user(email="collide@example.test")
    token = _invite(session, email="collide@example.test")

    response = anon_client.post(
        "/api/auth/setup", json={"token": token, "password": "a-good-password"}
    )
    assert response.status_code == 409
```

Move the two imports to the top of the file with the others when you write it; they are shown inline only to keep this task self-contained.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_api_auth.py -k setup -v`
Expected: FAIL — 404 on `/api/auth/setup`.

- [ ] **Step 3: Add the route**

In `src/reachstore/api/routes.py`, extend the `reachstore.api.auth` import with `MIN_PASSWORD_LENGTH`, `consume_invite`, and `hash_password`, extend the schemas import with `SetupRequest`, then append:

```python
@router.post("/auth/setup", response_model=UserOut)
def post_setup(
    body: SetupRequest, response: Response, session: Session = Depends(get_session)
) -> UserOut:
    """Redeem an invite: create the account and log it straight in.

    Unauthenticated by design -- it is how someone with no account gets one.
    Its access control is possession of a token that exists in exactly one
    place, the URL the operator handed over.

    One 400 with one message for every token failure -- unknown, already
    consumed, expired, password too short -- because distinguishing them would
    let a stranger probe which invites exist.

    An email that already has an account is the exception, and returns 409:
    whoever holds the token already knows the email it names, so the
    distinction leaks nothing they did not supply, and it is the one failure a
    person can act on.
    """
    now = datetime.now(UTC)

    # Validate the password BEFORE consuming the invite. Consuming first would
    # mean a typo burns a single-use link and the person has to go back to the
    # operator for a new one.
    if len(body.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail="invalid or expired setup link")

    invite = consume_invite(session, token=body.token, now=now)
    if invite is None:
        raise HTTPException(status_code=400, detail="invalid or expired setup link")

    taken = (
        session.execute(select(User).where(User.email == invite.email))
        .scalars()
        .one_or_none()
    )
    if taken is not None:
        # The invite predates an account that now exists. It is spent either
        # way -- rolling it back would leave a link that can be retried
        # forever against an existing account.
        session.commit()
        raise HTTPException(status_code=409, detail="that email already has an account")

    user = User(
        email=invite.email,
        display_name=invite.display_name,
        password_hash=hash_password(body.password),
        is_admin=invite.is_admin,
        created_at=now,
    )
    session.add(user)
    session.flush()

    token = create_session(session, user_id=user.id, now=now)
    session.commit()
    _set_session_cookie(response, token)
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_api_auth.py -v`
Expected: PASS (16 tests — 8 from Task 4 plus 8 here).

The 409 branch is the only setup failure that is not a uniform 400. If `Setup.jsx` (Task 9) is already written, its `err.status === 400` check will not cover it; Task 9's error copy handles 400 and falls through to `String(err)` for anything else, which is acceptable — a stale invite for a live account is an operator problem, not a user one.

- [ ] **Step 5: Redeem the real invite from Task 6**

Start the API and the frontend is not needed yet — redeem it over HTTP:

```bash
.venv/bin/python -c "from reachstore.api.app import serve; serve()" &
sleep 2
curl -s -X POST http://127.0.0.1:8000/api/auth/setup \
  -H 'Content-Type: application/json' \
  -d '{"token":"<PASTE THE TOKEN FROM TASK 6>","password":"<pick a real password>"}'
```

Expected: a JSON body with your email and `"is_admin": true`.

**Stop the server you started, and only that one.** Find its PID from the job you backgrounded (`jobs -l`), or use the PID the shell printed. If port 8000 is already taken by something you did not start, use a different port instead — `serve()` reads no port argument, so run `.venv/bin/python -c "import uvicorn; from reachstore.api.app import create_app; uvicorn.run(create_app(), host='127.0.0.1', port=8100)"` and adjust the curl URL. **Never kill a process you did not start.**

- [ ] **Step 6: Run the full suite and commit**

```bash
.venv/bin/pytest
git add src/reachstore/api tests/test_api_auth.py
git commit -m "feat: redeem an invite via POST /api/auth/setup"
```

---

### Task 8: Catalog and subscriptions

**Files:**
- Modify: `src/reachstore/query.py`, `src/reachstore/store.py`, `src/reachstore/api/schemas.py`, `src/reachstore/api/routes.py`
- Test: `tests/test_api_subscriptions.py`

**Interfaces:**
- Consumes: `get_current_user` (Task 2); `query.search`'s existing `subscribed_only` parameter
- Produces:
  ```python
  # query.py
  @dataclass(frozen=True)
  class CatalogEntry:
      source_id: int; kind: str; identifier: str; tier: int; subscribed: bool

  catalog(session, *, user_id: int) -> list[CatalogEntry]

  # store.py
  subscribe(session, *, user_id: int, source_id: int, now: datetime) -> None
  unsubscribe(session, *, user_id: int, source_id: int) -> None

  # routes
  GET    /api/catalog                   -> CatalogResponse
  PUT    /api/subscriptions/{source_id} -> 204
  DELETE /api/subscriptions/{source_id} -> 204
  GET    /api/search?...&subscribed_only=true
  ```

`query.search` has had a `subscribed_only` parameter since Plan 1 and has never had a caller — there was no way to create a subscription. This task gives it one.

**PUT, not POST, for subscribe.** The request means "make this subscription exist", which is idempotent by definition, so the verb should be too. Idempotency is enforced by `ON CONFLICT`, not by reading first: a check-then-insert has a window where two concurrent requests both see nothing and both insert, and one gets an IntegrityError.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_subscriptions.py`:

```python
from datetime import UTC, datetime

from reachstore.adapters.base import NormalizedItem
from reachstore.models import Source
from reachstore.store import upsert_items

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


def make_source(session, identifier, *, tier=1, kind="rss"):
    source = Source(
        kind=kind, identifier=identifier, tier=tier, config_json={}, created_at=NOW
    )
    session.add(source)
    session.flush()
    return source


def add_item(session, source, *, external_id, text, raw_dir):
    upsert_items(
        session,
        source_id=source.id,
        items=[
            NormalizedItem(
                external_id=external_id,
                url=f"https://x/{external_id}",
                title=external_id,
                content_text=text,
                published_at=NOW,
            )
        ],
        owner_user_id=None,
        raw_dir=raw_dir,
        now=NOW,
    )
    session.flush()


# --- catalog -----------------------------------------------------------------

def test_catalog_lists_every_source_with_a_subscribed_flag(session, user_client):
    make_source(session, "https://a/feed")
    make_source(session, "https://b/feed", tier=2)

    body = user_client.get("/api/catalog").json()
    rows = {r["identifier"]: r for r in body["sources"]}
    assert set(rows) == {"https://a/feed", "https://b/feed"}
    assert rows["https://a/feed"]["subscribed"] is False
    assert rows["https://b/feed"]["tier"] == 2


def test_catalog_reflects_only_the_requesting_users_subscriptions(session, client_for):
    alice_client, _alice, _ = client_for()
    bob_client, _bob, _ = client_for()
    source = make_source(session, "https://shared/feed")

    assert alice_client.put(f"/api/subscriptions/{source.id}").status_code == 204

    def subscribed(client):
        return client.get("/api/catalog").json()["sources"][0]["subscribed"]

    assert subscribed(alice_client) is True
    assert subscribed(bob_client) is False


def test_catalog_omits_health_and_error_fields(session, user_client):
    """The catalog is the non-admin view. Diagnostics stay on /api/sources."""
    make_source(session, "https://a/feed")
    row = user_client.get("/api/catalog").json()["sources"][0]
    assert set(row) == {"source_id", "kind", "identifier", "tier", "subscribed"}


# --- subscribe / unsubscribe -------------------------------------------------

def test_subscribe_is_idempotent(session, user_client):
    source = make_source(session, "https://a/feed")
    for _ in range(3):
        assert user_client.put(f"/api/subscriptions/{source.id}").status_code == 204
    assert user_client.get("/api/catalog").json()["sources"][0]["subscribed"] is True


def test_unsubscribe_is_idempotent_and_works_when_never_subscribed(session, user_client):
    source = make_source(session, "https://a/feed")
    for _ in range(3):
        assert user_client.delete(f"/api/subscriptions/{source.id}").status_code == 204
    assert user_client.get("/api/catalog").json()["sources"][0]["subscribed"] is False


def test_resubscribing_after_unsubscribing_works(session, user_client):
    """Unsubscribe clears the `active` flag rather than deleting the row, so
    re-subscribing has to reactivate it -- a plain insert would conflict."""
    source = make_source(session, "https://a/feed")
    user_client.put(f"/api/subscriptions/{source.id}")
    user_client.delete(f"/api/subscriptions/{source.id}")
    assert user_client.put(f"/api/subscriptions/{source.id}").status_code == 204
    assert user_client.get("/api/catalog").json()["sources"][0]["subscribed"] is True


def test_subscribing_to_an_unknown_source_is_404(user_client):
    assert user_client.put("/api/subscriptions/999999").status_code == 404


# --- subscribed_only search --------------------------------------------------

def test_search_subscribed_only_filters_by_subscription(session, user_client, raw_dir):
    a = make_source(session, "https://a/feed")
    b = make_source(session, "https://b/feed")
    add_item(session, a, external_id="from-a", text="shared keyword", raw_dir=raw_dir)
    add_item(session, b, external_id="from-b", text="shared keyword", raw_dir=raw_dir)
    user_client.put(f"/api/subscriptions/{a.id}")

    everything = user_client.get("/api/search?q=keyword").json()["items"]
    assert len(everything) == 2

    filtered = user_client.get("/api/search?q=keyword&subscribed_only=true").json()["items"]
    assert [i["title"] for i in filtered] == ["from-a"]


def test_subscribed_only_defaults_to_false(session, user_client, raw_dir):
    """Reading is unfiltered unless asked. Subscriptions narrow the view; they
    do not gate access -- collection stays tier-driven."""
    a = make_source(session, "https://a/feed")
    add_item(session, a, external_id="from-a", text="shared keyword", raw_dir=raw_dir)

    assert len(user_client.get("/api/search?q=keyword").json()["items"]) == 1


def test_unsubscribing_removes_items_from_a_subscribed_only_search(session, user_client, raw_dir):
    a = make_source(session, "https://a/feed")
    add_item(session, a, external_id="from-a", text="shared keyword", raw_dir=raw_dir)
    user_client.put(f"/api/subscriptions/{a.id}")
    user_client.delete(f"/api/subscriptions/{a.id}")

    assert user_client.get("/api/search?q=keyword&subscribed_only=true").json()["items"] == []


def test_catalog_requires_a_session(anon_client):
    assert anon_client.get("/api/catalog").status_code == 401


def test_subscribing_requires_a_session(anon_client):
    assert anon_client.put("/api/subscriptions/1").status_code == 401
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_api_subscriptions.py -v`
Expected: FAIL — 404 on `/api/catalog` and on the subscription routes.

- [ ] **Step 3: Add `query.catalog`**

In `src/reachstore/query.py`, add beside the existing `SourceStatus` dataclass:

```python
@dataclass(frozen=True)
class CatalogEntry:
    """A source as a non-admin sees it: enough to decide whether to subscribe,
    and nothing about its health. Diagnostics stay in SourceStatus, which only
    /api/sources returns."""

    source_id: int
    kind: str
    identifier: str
    tier: int
    subscribed: bool
```

And the reader:

```python
def catalog(session: Session, *, user_id: int) -> list[CatalogEntry]:
    """Every source, flagged with whether this user subscribes to it.

    A LEFT JOIN rather than two queries and a set intersection: one round trip,
    and the flag cannot drift from the row it describes.
    """
    rows = session.execute(
        select(
            Source.id,
            Source.kind,
            Source.identifier,
            Source.tier,
            Subscription.id.isnot(None),
        )
        .select_from(Source)
        .outerjoin(
            Subscription,
            (Subscription.source_id == Source.id)
            & (Subscription.user_id == user_id)
            & (Subscription.active.is_(True)),
        )
        .order_by(Source.tier, Source.identifier)
    ).all()
    return [
        CatalogEntry(
            source_id=r[0], kind=r[1], identifier=r[2], tier=r[3], subscribed=bool(r[4])
        )
        for r in rows
    ]
```

**Add no imports to `query.py`.** It already has `dataclass`, `select`, `Session`, and `Subscription` — its import block was read to confirm this.

- [ ] **Step 4: Add the writers to `store.py`**

In `src/reachstore/store.py`:

```python
def subscribe(session: Session, *, user_id: int, source_id: int, now: datetime) -> None:
    """Idempotent. Reactivates a row left inactive by `unsubscribe`.

    ON CONFLICT rather than a read-then-insert: two concurrent requests would
    both see no row and both insert, and one would get an IntegrityError from
    uq_subscriptions_user_source. The database settles it in one statement --
    the same reasoning as upsert_items.
    """
    session.execute(
        insert(Subscription)
        .values(user_id=user_id, source_id=source_id, active=True, created_at=now)
        .on_conflict_do_update(
            constraint="uq_subscriptions_user_source", set_={"active": True}
        )
    )


def unsubscribe(session: Session, *, user_id: int, source_id: int) -> None:
    """Idempotent: clears `active`, and updating zero rows is not an error.

    The row survives so that re-subscribing keeps the original created_at and
    any label, and so `subscribe`'s ON CONFLICT has something to update.
    """
    session.execute(
        update(Subscription)
        .where(Subscription.user_id == user_id, Subscription.source_id == source_id)
        .values(active=False)
    )
```

Imports, stated exactly — `store.py`'s current import block was read to confirm each of these:

- It already has `from sqlalchemy.dialects.postgresql import insert` (**no alias**). Use the bare name `insert`; do not add a second aliased import of the same symbol.
- It has **no** `from sqlalchemy import ...` line at all. Add one: `from sqlalchemy import update`.
- It imports `from reachstore.models import Item`. Extend that line to `from reachstore.models import Item, Subscription`.
- `datetime` and `Session` are already imported.

- [ ] **Step 5: Add the schemas**

Append to `src/reachstore/api/schemas.py`:

```python
class CatalogEntryOut(BaseModel):
    """Mirrors query.CatalogEntry; built via CatalogEntryOut(**vars(e)).

    Same extra="forbid" reasoning as SourceStatusOut: pydantic already raises
    on a missing field but silently drops an extra one, so forbidding extras
    makes a dataclass/schema mismatch fail in both directions.
    """

    model_config = ConfigDict(extra="forbid")

    source_id: int
    kind: str
    identifier: str
    tier: int
    subscribed: bool


class CatalogResponse(BaseModel):
    sources: list[CatalogEntryOut]
```

- [ ] **Step 6: Add the routes**

In `src/reachstore/api/routes.py`, extend the schemas import with `CatalogEntryOut` and `CatalogResponse`, add `Source` to the models import, and append:

```python
@router.get("/catalog", response_model=CatalogResponse)
def get_catalog(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> CatalogResponse:
    """Every source, with this user's subscription flag.

    Not admin-gated, because a non-admin has to see sources in order to
    subscribe to them -- and `source_identifier` already appears on every feed
    row, so identifiers were never operator-only. What is operator-only is the
    health and control surface on /api/sources.
    """
    entries = query.catalog(session, user_id=user.id)
    return CatalogResponse(sources=[CatalogEntryOut(**vars(e)) for e in entries])


@router.put("/subscriptions/{source_id}", status_code=204, response_class=Response)
def put_subscription(
    source_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    """PUT, not POST: the request means "make this subscription exist", which
    is idempotent by definition, so the verb is too.

    Returns an explicit empty Response rather than None. A 204 must carry no
    body, and letting FastAPI serialise a None return value through the
    default JSON response class is the kind of detail that differs between
    versions -- being explicit costs one line and cannot regress.
    """
    if session.get(Source, source_id) is None:
        raise HTTPException(status_code=404, detail="source not found")
    store.subscribe(session, user_id=user.id, source_id=source_id, now=datetime.now(UTC))
    session.commit()
    return Response(status_code=204)


@router.delete("/subscriptions/{source_id}", status_code=204, response_class=Response)
def delete_subscription(
    source_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    """204 even when no subscription existed -- the caller's desired state is
    reached either way, and a 404 here would leak nothing useful."""
    store.unsubscribe(session, user_id=user.id, source_id=source_id)
    session.commit()
    return Response(status_code=204)
```

Add `from reachstore import query, store` — `routes.py` currently imports only `query`. `Response` is already imported from `fastapi`.

Verify the empty body rather than assuming it:

```bash
.venv/bin/python -c "
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
app = FastAPI()
@app.put('/x', status_code=204, response_class=Response)
def x() -> Response: return Response(status_code=204)
r = TestClient(app).put('/x')
print(r.status_code, repr(r.content))"
```

Expected: `204 b''`.

- [ ] **Step 7: Add `subscribed_only` to search**

```python
@router.get("/search", response_model=SearchResponse)
def get_search(
    q: str = Query(..., min_length=1),
    kind: str | None = None,
    limit: int = Query(50, ge=1, le=query.MAX_LIMIT),
    subscribed_only: bool = False,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SearchResponse:
    """`subscribed_only` narrows reading only.

    Collection stays tier-driven: unsubscribing hides a source from your view
    without stopping it being collected, and without affecting anyone else.
    Filtering at read time is reversible; filtering at ingest is not.
    """
    items = query.search(
        session,
        user_id=user.id,
        q=q,
        kinds=[kind] if kind else None,
        subscribed_only=subscribed_only,
        limit=limit,
    )
    return SearchResponse(items=[_summary(i) for i in items])
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_api_subscriptions.py -v`
Expected: PASS (12 tests).

- [ ] **Step 9: Add the two new endpoints to the permission matrix**

In `tests/test_api_permissions.py`, add to `CASES`:

```python
    ("GET", "/api/catalog", 401, 200, 200),
    ("DELETE", "/api/subscriptions/999999", 401, 204, 204),
```

`PUT /api/subscriptions/{id}` is not in the table because it 404s on an id that does not exist, which would need a seeded source; `test_subscribing_requires_a_session` covers its anonymous case.

**Also close three gaps the Task 5 review found in this file.** They were inherited from my plan text, and this task is the right moment because it is the first task to add new endpoints — exactly what the file's own docstring claims to catch.

1. **Make the docstring's promise real.** `test_api_permissions.py` opens by claiming "A new endpoint added without a row here is the failure this file exists to catch" — but nothing enumerates the app's routes, so a new endpoint with no row leaves the file green. Add:

```python
def test_every_api_route_is_in_the_matrix():
    """Makes this file's opening claim true rather than aspirational.

    Without this, a new endpoint added with no CASES row leaves the suite
    green and its access level unasserted -- which is precisely how an
    endpoint ships unauthenticated.
    """
    from reachstore.api.app import create_app

    # Exempt by design, each for a stated reason:
    #   /api/auth/login  - must be reachable anonymously; that IS its contract
    #   /api/auth/setup  - same, and it is covered by tests/test_api_auth.py
    #   /api/collect     - covered by test_collect_is_admin_only, which needs
    #                      a stubbed runner the table-driven test cannot supply
    #   /api/docs, /api/openapi.json - FastAPI's own, not ours
    EXEMPT = {
        "/api/auth/login",
        "/api/auth/setup",
        "/api/collect",
        "/api/docs",
        "/api/openapi.json",
    }
    covered = {path.split("?")[0] for _method, path, *_ in CASES}
    missing = []
    for route in create_app().routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api") or path in EXEMPT or path in covered:
            continue
        missing.append(path)
    assert not missing, f"endpoints with no permission-matrix row: {sorted(set(missing))}"
```

Note `covered` strips the query string, because `CASES` holds `/api/search?q=anything` while the route's own path is `/api/search`.

2. **Make the collect stub match the real contract.** `no_op_collect` currently uses `lambda tier, force: None`, but the real `run_collection` clears `_running` in its `finally` (`collect_runner.py:105-107`). The stub leaves it `True`. Cross-test leakage is already prevented by conftest's autouse reset, but a second admin `POST /api/collect` inside one test would get an unexplained 409. Change it to:

```python
    monkeypatch.setattr(
        collect_runner,
        "run_collection",
        lambda tier, force: setattr(collect_runner, "_running", False),
    )
```

3. **Name the role in the matrix failure message.** `{client}` renders as `<starlette.testclient.TestClient object at 0x...>`, which tells you nothing about which role failed — in the one test guarding the auth boundary. Label the tuples:

```python
    for label, client, expected in (
        ("anon", anon_client, anon),
        ("user", user_client, user),
        ("admin", admin_client, admin),
    ):
        response = client.request(method, path)
        assert response.status_code == expected, (
            f"{method} {path} as {label}: expected {expected}, got {response.status_code}"
        )
```

- [ ] **Step 10: Run the full suite and commit**

```bash
.venv/bin/pytest
git add src/reachstore tests/
git commit -m "feat: source catalog, idempotent subscriptions, subscribed-only search"
```

---

### Task 9: Frontend — the login gate

**Files:**
- Modify: `web/src/api.js`, `web/src/App.jsx`, `web/src/components/SearchBar.jsx`, `web/src/styles.css`
- Create: `web/src/components/Login.jsx`, `web/src/components/Setup.jsx`, `web/src/components/Store.jsx`

**Interfaces:**
- Consumes: `/api/auth/me`, `/api/auth/login`, `/api/auth/setup`, `/api/auth/logout` (Tasks 4 and 7)
- Produces: `ApiError` (carries `.status`), `fetchMe`, `login`, `setupAccount`, `logout`; the `Store` component holding what `App` used to be

**One deviation from the spec, with reasoning — read this before starting.**

The spec put the setup link at `<WEB_BASE_URL>/?setup=<token>` — a query string on the root path. **This plan uses a fragment instead: `<WEB_BASE_URL>/#setup=<token>`.**

Both forms keep the path at `/`, which matters and which the spec got right: `create_app()` mounts `StaticFiles(directory=WEB_DIST, html=True)`, and Starlette's `html=True` serves `index.html` for *directory* requests while looking for `404.html` on a miss — it is not an SPA history fallback. A real `/setup` path would therefore 404 in production even though the Vite dev server would serve it. Neither form has that problem.

The single reason to prefer the fragment: **a URL fragment is never sent to the server.** A query string lands in the access log, in any proxy log, and in the `Referer` header of the next outbound request — so a single-use credential would sit in three places it has no reason to be. The fragment costs nothing and avoids all three.

`App` reads it with `new URLSearchParams(location.hash.slice(1)).get('setup')`.

**Structural change — the reason it is unavoidable.** Today `App` owns 9 `useState` calls and 6 `useRef` calls, and its mount effect immediately calls `loadFeed()` and `refreshSources()`. Those hooks cannot be conditional — React requires the same hooks on every render — so they would fire against `/api/feed` and `/api/sources` before anyone has logged in and paint two 401 error banners over the login form. The whole current body therefore moves verbatim into `web/src/components/Store.jsx`, and `App.jsx` becomes just the gate. `Store` does not mount until `me` is set, so its hooks never run unauthenticated.

- [ ] **Step 1: Rewrite `web/src/api.js`**

```js
// Status-carrying error: the login gate has to tell "not logged in" (401)
// apart from a real failure, and `new Error('401 Unauthorized')` would force
// callers to parse a string to find out.
export class ApiError extends Error {
  constructor(status, statusText) {
    super(`${status} ${statusText}`)
    this.status = status
  }
}

async function get(path, params) {
  const qs = params ? '?' + new URLSearchParams(params) : ''
  const res = await fetch(`/api${path}${qs}`)
  if (!res.ok) throw new ApiError(res.status, res.statusText)
  return res.json()
}

// Cookies ride along because fetch defaults to credentials: 'same-origin'
// and the Vite proxy keeps the browser same-origin. That default is also why
// no CORS middleware exists anywhere in this project.
async function send(method, path, body) {
  const res = await fetch(`/api${path}`, {
    method,
    ...(body === undefined
      ? {}
      : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  })
  if (!res.ok) throw new ApiError(res.status, res.statusText)
  return res.status === 204 ? null : res.json()
}

export function fetchFeed(cursor, limit = 50) {
  const params = { limit }
  if (cursor) {
    params.before_id = cursor.id
    // Omit the key entirely when the cursor row had no published_at. Sending
    // an empty string is a 422, and omitting it is also the correct meaning:
    // the server reads a bare before_id as "continue through the NULLS LAST
    // tail".
    if (cursor.published_at !== null) params.before_published_at = cursor.published_at
  }
  return get('/feed', params)
}

export const fetchSearch = (q, kind, subscribedOnly = false) =>
  get('/search', {
    q,
    ...(kind ? { kind } : {}),
    ...(subscribedOnly ? { subscribed_only: true } : {}),
  })
export const fetchItem = (id) => get(`/items/${id}`)
export const fetchSources = () => get('/sources')

// null, not a throw: "nobody is logged in" is the expected answer on a first
// visit, not a failure worth showing the user.
export async function fetchMe() {
  try {
    return await get('/auth/me')
  } catch (e) {
    if (e.status === 401) return null
    throw e
  }
}

export const login = (email, password) => send('POST', '/auth/login', { email, password })
export const setupAccount = (token, password) => send('POST', '/auth/setup', { token, password })
export const logout = () => send('POST', '/auth/logout')

export const fetchCatalog = () => get('/catalog')
export const subscribe = (sourceId) => send('PUT', `/subscriptions/${sourceId}`)
export const unsubscribe = (sourceId) => send('DELETE', `/subscriptions/${sourceId}`)

export async function startCollect(tier, force = false) {
  const res = await fetch('/api/collect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tier, force }),
  })
  return { ok: res.ok, ...(await res.json()) }
}
```

- [ ] **Step 2: Create `web/src/components/Login.jsx`**

```js
import { useState } from 'react'
import { login } from '../api'

export default function Login({ onDone }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      onDone(await login(email, password))
    } catch (err) {
      // One message for a wrong password and an unknown email, matching the
      // server's single 401 -- the UI must not reintroduce the distinction the
      // API deliberately hides.
      setError(err.status === 401 ? 'Email or password is incorrect.' : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="auth" onSubmit={submit}>
      <h1>reachstore</h1>
      <label htmlFor="email">Email</label>
      <input
        id="email"
        type="email"
        autoComplete="username"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        required
      />
      <label htmlFor="password">Password</label>
      <input
        id="password"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
      />
      {error && <p className="error">{error}</p>}
      <button type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
      <p className="auth-note">
        Accounts are created by invitation. Ask whoever runs this instance for a
        setup link.
      </p>
    </form>
  )
}
```

`type="submit"` with `busy` disabling it is the guard here, rather than the `useRef` pattern `Store` uses: a disabled submit button cannot be double-fired the way `loadMore`'s plain button could, because the browser blocks the second submit before React sees it.

- [ ] **Step 3: Create `web/src/components/Setup.jsx`**

```js
import { useState } from 'react'
import { setupAccount } from '../api'

const MIN_PASSWORD_LENGTH = 8

export default function Setup({ token, onDone }) {
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    if (busy) return
    // Checked here as well as on the server: catching a mismatch or a short
    // password before the request keeps a single-use link from being spent on
    // a typo. The server is still the authority.
    if (password !== confirm) return setError('The two passwords do not match.')
    if (password.length < MIN_PASSWORD_LENGTH) {
      return setError(`Use at least ${MIN_PASSWORD_LENGTH} characters.`)
    }
    setBusy(true)
    setError(null)
    try {
      const me = await setupAccount(token, password)
      // Clear the token from the address bar so a reload does not retry a link
      // that is now spent.
      history.replaceState(null, '', location.pathname)
      onDone(me)
    } catch (err) {
      setError(
        err.status === 400
          ? 'This setup link is invalid, expired, or already used. Ask for a new one.'
          : String(err)
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="auth" onSubmit={submit}>
      <h1>Choose a password</h1>
      <label htmlFor="new-password">Password</label>
      <input
        id="new-password"
        type="password"
        autoComplete="new-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
      />
      <label htmlFor="confirm-password">Confirm password</label>
      <input
        id="confirm-password"
        type="password"
        autoComplete="new-password"
        value={confirm}
        onChange={(e) => setConfirm(e.target.value)}
        required
      />
      {error && <p className="error">{error}</p>}
      <button type="submit" disabled={busy}>{busy ? 'Creating…' : 'Create account'}</button>
    </form>
  )
}
```

- [ ] **Step 4: Create `web/src/components/Store.jsx`**

Move the **entire current body of `App.jsx`** — every `useState`, every `useRef` with its comment, `fail`, `loadFeed`, `refreshSources`, both effects, `select`, `search`, `loadMore`, `collect`, and the returned JSX — into this file, renamed `Store`, with these changes and no others:

1. Signature and imports:

```js
import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchFeed, fetchItem, fetchSearch, fetchSources, logout, startCollect } from '../api'
import HealthStrip from './HealthStrip'
import ItemDetail from './ItemDetail'
import ItemList from './ItemList'
import SearchBar from './SearchBar'

export default function Store({ me, onSignedOut }) {
```

2. `fail` learns about expiry:

```js
  // A 401 mid-session means the cookie was revoked or expired. Dropping back
  // to the login form is the truthful response; showing "401 Unauthorized" in
  // the error banner would leave a dead UI on screen.
  const fail = (e) => (e.status === 401 ? onSignedOut() : setError(String(e)))
```

3. `refreshSources` becomes admin-only. `/api/sources` returns 403 to a non-admin, so calling it unconditionally would paint an error banner for every ordinary user on page load:

```js
  const refreshSources = useCallback(() => {
    if (!me.is_admin) return Promise.resolve()
    const reqId = ++sourcesIdRef.current
    return fetchSources()
      .then((r) => {
        if (sourcesIdRef.current !== reqId) return
        setSources(r.sources); setCollecting(r.collecting)
      })
      .catch(fail)
  }, [me.is_admin])
```

4. Add a sign-out handler:

```js
  const signOut = async () => {
    try { await logout() } finally { onSignedOut() }
  }
```

`finally` rather than `then`: if the logout request fails the local session is still gone as far as this browser is concerned, and leaving the user apparently signed in would be worse than a lost round trip.

5. The header gates the operator surface on `me.is_admin` and gains the sign-out control:

```js
      <header className="header">
        <SearchBar
          onSearch={search}
          onClear={loadFeed}
          onCollect={collect}
          collecting={collecting || collectPending}
          canCollect={me.is_admin}
        />
        <div className="header-row">
          {me.is_admin && <HealthStrip sources={sources} />}
          <span className="whoami">
            {me.display_name}
            {me.is_admin && <span className="badge">admin</span>}
            <button className="signout" onClick={signOut}>sign out</button>
          </span>
        </div>
      </header>
```

Leave the polling effect's dependency array as `[collecting, loadFeed]`. It only runs while `collecting` is true, which only a collect can cause, which only an admin can trigger.

- [ ] **Step 5: Rewrite `web/src/App.jsx` as the gate**

```js
import { useCallback, useEffect, useState } from 'react'
import { fetchMe } from './api'
import Login from './components/Login'
import Setup from './components/Setup'
import Store from './components/Store'

// A fragment, not a query string: `/#setup=<token>` never reaches the server,
// so a single-use credential stays out of access logs, proxy logs, and the
// Referer header. The path stays `/` either way, which matters -- a real
// `/setup` path would 404 in production, because StaticFiles's html=True
// looks for 404.html rather than falling back to index.html.
const readSetupToken = () =>
  new URLSearchParams(window.location.hash.slice(1)).get('setup')

export default function App() {
  // undefined = still asking the server, null = signed out, object = signed in.
  // Three states, not two: rendering the login form while the check is still in
  // flight makes an already-signed-in user see a login flash on every reload.
  const [me, setMe] = useState(undefined)
  const [setupToken, setSetupToken] = useState(readSetupToken)

  useEffect(() => { fetchMe().then(setMe).catch(() => setMe(null)) }, [])

  const signedOut = useCallback(() => {
    setMe(null)
    // Drop any stale token so signing out does not bounce into the setup form.
    setSetupToken(null)
  }, [])

  if (me === undefined) return <p className="booting">…</p>
  if (me === null) {
    return setupToken
      ? <Setup token={setupToken} onDone={setMe} />
      : <Login onDone={setMe} />
  }
  return <Store me={me} onSignedOut={signedOut} />
}
```

- [ ] **Step 6: Gate the collect controls in `SearchBar.jsx`**

Change the signature to accept `canCollect` and wrap the tier select and collect button:

```js
export default function SearchBar({ onSearch, onClear, onCollect, collecting, canCollect }) {
```

```js
      {canCollect && (
        <>
          <select value={tier} onChange={(e) => setTier(Number(e.target.value))} aria-label="tier">
            <option value={1}>Tier 1</option>
            <option value={2}>Tier 2</option>
            <option value={3}>Tier 3</option>
          </select>
          <button type="button" onClick={() => onCollect(tier)} disabled={collecting}>
            {collecting ? 'Collecting…' : 'Collect'}
          </button>
        </>
      )}
```

Hiding the control is presentation, not security — `POST /api/collect` returns 403 to a non-admin regardless, which is what `test_collect_is_admin_only` pins. Both layers are needed: the server one to be correct, this one so an ordinary user is not shown a button that always fails.

- [ ] **Step 7: Add the styles**

Append to `web/src/styles.css`:

```css
.booting { color:var(--dim); padding:2rem; text-align:center; }
.auth { max-width:20rem; margin:4rem auto; display:flex; flex-direction:column; gap:.35rem; }
.auth h1 { font-size:1.15rem; margin:0 0 .8rem; }
.auth label { font-size:.78rem; color:var(--dim); }
.auth input { padding:.45rem .6rem; background:#1a1a1a; color:var(--fg);
  border:1px solid var(--line); border-radius:4px; font:inherit; }
.auth button { margin-top:.7rem; padding:.5rem; background:var(--accent); color:#0b0b0b;
  border:0; border-radius:4px; cursor:pointer; font:inherit; font-weight:600; }
.auth button:disabled { opacity:.55; cursor:default; }
.auth-note { color:var(--dim); font-size:.75rem; margin:.9rem 0 0; }
.header-row { display:flex; align-items:baseline; justify-content:space-between; gap:1rem; }
.whoami { color:var(--dim); font-size:.78rem; white-space:nowrap; }
.badge { margin-left:.4rem; padding:.05rem .3rem; border:1px solid var(--line);
  border-radius:3px; font-size:.68rem; }
.signout { margin-left:.6rem; background:none; border:0; color:var(--accent);
  cursor:pointer; font:inherit; font-size:.78rem; padding:0; }
```

- [ ] **Step 8: Verify the build and lint**

```bash
cd /Users/dev2/Desktop/Testing/web && npm run build
```

Expected: clean. A failure here is almost always an unresolved import left behind in `App.jsx` after the body moved to `Store.jsx`.

**There is no `npm run lint`.** This project has never had ESLint — `web/package.json` defines only `dev`, `build`, `preview`, `seed:e2e`, and `test:e2e`, and there is no eslint config file. Do not add one: the global constraints forbid new dependencies, and wiring up a linter is not part of an auth slice. `vite build` is the build gate.

- [ ] **Step 9: Verify by hand in a browser**

Start the API and the dev server, log in with the admin account you created in Tasks 6 and 7, and confirm:
- an anonymous visit shows the login form, not an error banner
- a wrong password shows "Email or password is incorrect."
- after signing in, the feed loads and the health strip and Collect button are present
- sign out returns to the login form
- reloading while signed in shows the feed with no login flash

**If port 8000 or 5173 is already in use by a process you did not start, pick another port. Never kill a process you did not start.**

- [ ] **Step 10: Commit**

```bash
cd /Users/dev2/Desktop/Testing
git add web/src
git commit -m "feat: login gate, setup form, sign out, admin-gated operator controls"
```

---

### Task 10: Frontend — subscriptions

**Files:**
- Create: `web/src/components/SubscriptionStrip.jsx`
- Modify: `web/src/components/Store.jsx`, `web/src/components/SearchBar.jsx`, `web/src/styles.css`

**Interfaces:**
- Consumes: `fetchCatalog`, `subscribe`, `unsubscribe`, `fetchSearch(q, kind, subscribedOnly)` (Tasks 8 and 9)
- Produces: the `SubscriptionStrip` component; a subscribed-only toggle wired through `Store`'s `search`

- [ ] **Step 1: Create `web/src/components/SubscriptionStrip.jsx`**

```js
import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchCatalog, subscribe, unsubscribe } from '../api'

export default function SubscriptionStrip({ onError }) {
  const [open, setOpen] = useState(false)
  const [entries, setEntries] = useState([])

  // Same ordering-guard shape as Store's sourcesIdRef: toggling several rows
  // quickly fires several catalog reloads, and a slow earlier response landing
  // after a newer one would reinstate checkboxes the user has since changed.
  const reqIdRef = useRef(0)

  // Per-row in-flight set, held in a ref rather than state for the same reason
  // Store's loadMore guard is a ref: React batches state updates, so two
  // same-tick clicks on one row would both read the pre-click value and send
  // two requests.
  const pendingRef = useRef(new Set())

  const reload = useCallback(() => {
    const reqId = ++reqIdRef.current
    return fetchCatalog()
      .then((r) => { if (reqIdRef.current === reqId) setEntries(r.sources) })
      .catch(onError)
  }, [onError])

  useEffect(() => { if (open) reload() }, [open, reload])

  const toggle = async (entry) => {
    if (pendingRef.current.has(entry.source_id)) return
    pendingRef.current.add(entry.source_id)
    try {
      await (entry.subscribed ? unsubscribe : subscribe)(entry.source_id)
      await reload()
    } catch (e) {
      onError(e)
    } finally {
      pendingRef.current.delete(entry.source_id)
    }
  }

  const count = entries.filter((e) => e.subscribed).length

  return (
    <div className="subs">
      <button className="subs-summary" onClick={() => setOpen(!open)}>
        {open ? '▾' : '▸'} subscriptions{open && ` · ${count} of ${entries.length}`}
      </button>
      {open && (
        <ul className="subs-list">
          {entries.length === 0 && <li className="empty">no sources yet</li>}
          {entries.map((e) => (
            <li key={e.source_id}>
              <label>
                <input
                  type="checkbox"
                  checked={e.subscribed}
                  onChange={() => toggle(e)}
                />
                <span className="subs-id">{e.identifier}</span>
                <span className="subs-meta">tier {e.tier} · {e.kind}</span>
              </label>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
```

The strip re-reads the catalog after every toggle rather than mutating local state. One extra request per click buys a checkbox that always reflects the database — and unlike an optimistic flip, it cannot leave the UI disagreeing with the server after a failed request.

- [ ] **Step 2: Add the subscribed-only toggle to `SearchBar.jsx`**

Extend the signature and add the checkbox before the clear button:

```js
export default function SearchBar({
  onSearch, onClear, onCollect, collecting, canCollect,
  subscribedOnly, onSubscribedOnlyChange,
}) {
```

```js
      <label className="subs-only">
        <input
          type="checkbox"
          checked={subscribedOnly}
          onChange={(e) => onSubscribedOnlyChange(e.target.checked)}
          aria-label="subscribed only"
        />
        subscribed only
      </label>
```

`SearchBar` gets only the checkbox and the two new props — **do not touch `submit`.** Re-running an active search on toggle is `Store.changeSubscribedOnly`'s job (Step 3). Two components both re-running the query would fire duplicate requests on every toggle.

- [ ] **Step 3: Wire it through `Store.jsx`**

Add the state, next to the existing `searching`:

```js
  const [subscribedOnly, setSubscribedOnly] = useState(false)

  // Mirrors subscribedOnly for the same reason searchingRef mirrors
  // `searching`: the last query has to be re-runnable from a callback that
  // would otherwise close over a stale value.
  const lastQueryRef = useRef(null)
```

Change `search` to remember the query and pass the flag:

```js
  const search = (q, onlySubscribed = subscribedOnly) => {
    searchingRef.current = true
    lastQueryRef.current = q
    setSearching(true)
    setError(null)
    const reqId = ++requestIdRef.current
    fetchSearch(q, null, onlySubscribed)
      .then((r) => {
        if (requestIdRef.current !== reqId) return
        setItems(r.items); setCursor(null)
      })
      .catch((e) => { if (requestIdRef.current === reqId) fail(e) })
  }
```

Add the handler:

```js
  // Re-run the active search immediately so the checkbox has a visible
  // effect. With no search active the flag only applies to /api/search, so
  // there is nothing to re-run -- the feed is deliberately unfiltered.
  const changeSubscribedOnly = (next) => {
    setSubscribedOnly(next)
    if (searchingRef.current && lastQueryRef.current) search(lastQueryRef.current, next)
  }
```

Clear the remembered query in `loadFeed`, right after `searchingRef.current = false`:

```js
    lastQueryRef.current = null
```

Then pass the props and render the strip:

```js
        <SearchBar
          onSearch={search}
          onClear={loadFeed}
          onCollect={collect}
          collecting={collecting || collectPending}
          canCollect={me.is_admin}
          subscribedOnly={subscribedOnly}
          onSubscribedOnlyChange={changeSubscribedOnly}
        />
        <div className="header-row">
          {me.is_admin && <HealthStrip sources={sources} />}
          <SubscriptionStrip onError={fail} />
          <span className="whoami">
            {me.display_name}
            {me.is_admin && <span className="badge">admin</span>}
            <button className="signout" onClick={signOut}>sign out</button>
          </span>
        </div>
```

Import `SubscriptionStrip` at the top.

`onError={fail}` reuses `Store`'s handler, so a 401 from a subscription request drops to the login form exactly like any other expired-session response, instead of showing a dead error banner.

**`subscribed_only` applies to search only, not to the feed.** That is the decision from the spec's §8: subscriptions narrow *reading*, and the feed stays the complete view. Do not add the parameter to `/api/feed` — `query.feed` has no such parameter, and adding one is out of scope for this plan.

- [ ] **Step 4: Add the styles**

Append to `web/src/styles.css`:

```css
.subs { font-size:.78rem; }
.subs-summary { background:none; border:0; color:var(--dim); cursor:pointer; font:inherit; padding:0; }
.subs-list { list-style:none; margin:.4rem 0 0; padding:0; max-height:11rem; overflow-y:auto; }
.subs-list li { padding:.15rem 0; }
.subs-list label { display:flex; align-items:center; gap:.4rem; cursor:pointer; }
.subs-id { flex:1; }
.subs-meta { color:var(--dim); font-size:.72rem; }
.subs-only { display:flex; align-items:center; gap:.3rem; color:var(--dim);
  font-size:.75rem; white-space:nowrap; }
```

- [ ] **Step 5: Verify the build and lint**

```bash
cd /Users/dev2/Desktop/Testing/web && npm run build
```

Expected: clean. There is no `npm run lint` in this project — see Task 9, Step 8.

- [ ] **Step 6: Verify by hand**

With the API and dev server running and signed in as the admin:
- expand `subscriptions` and confirm the seeded source is listed and unchecked
- check it, collapse and re-expand, and confirm it stays checked (it came from the database, not local state)
- search a term that matches, tick `subscribed only`, confirm results stay
- uncheck the subscription, confirm a `subscribed only` search now returns nothing
- confirm the plain feed still shows everything

- [ ] **Step 7: Commit**

```bash
cd /Users/dev2/Desktop/Testing
git add web/src
git commit -m "feat: subscription strip and subscribed-only search filter"
```

---

### Task 11: End-to-end tests

**Files:**
- Modify: `web/tests/seed_e2e.py`, `web/tests/smoke.spec.js`, `web/playwright.config.js`
- Create: `web/tests/auth.spec.js`

**Interfaces:**
- Consumes: everything above
- Produces: a seeded admin account; every existing spec signs in first

**Every one of the four existing specs currently calls `page.goto('/')` and expects the feed.** They will all now land on the login form. Each needs to sign in first.

- [ ] **Step 1: Seed an admin account**

In `web/tests/seed_e2e.py`, add to the imports:

```python
from reachstore.api.auth import hash_password
from reachstore.models import User
```

Add the credentials as module constants next to `NOW`:

```python
# Credentials for the Playwright specs. Plain text on purpose: this account
# exists only in the *_test database, which pytest's engine fixture drops at
# the start of every run.
E2E_EMAIL = "e2e-admin@example.test"
E2E_PASSWORD = "e2e-password-1234"
```

And inside `main()`, before the items block:

```python
        user = session.execute(
            select(User).where(User.email == E2E_EMAIL)
        ).scalars().one_or_none()
        if user is None:
            user = User(
                email=E2E_EMAIL,
                display_name="E2E Admin",
                password_hash=hash_password(E2E_PASSWORD),
                is_admin=True,
                created_at=NOW,
            )
            session.add(user)
            session.flush()
```

Keep it inside the existing `if source is None` idempotency style — a check-then-create, matching how the source is handled, so re-running the seed adds nothing. Also extend the final print:

```python
        print(f"seeded {COUNT} items ({new} new) and admin {E2E_EMAIL} into {url.rsplit('/', 1)[-1]}")
```

- [ ] **Step 2: Add a shared sign-in helper and use it in `smoke.spec.js`**

At the top of `web/tests/smoke.spec.js`:

```js
import { expect, test } from '@playwright/test'

// Must match E2E_EMAIL / E2E_PASSWORD in web/tests/seed_e2e.py.
const EMAIL = 'e2e-admin@example.test'
const PASSWORD = 'e2e-password-1234'

async function signIn(page) {
  await page.goto('/')
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  // Wait for the store, not just the click: every later locator assumes the
  // feed has replaced the login form.
  await expect(page.locator('.item-list')).toBeVisible()
}
```

`{ exact: true }` on the password field matters — `getByLabel('Password')` alone also matches "Confirm password" on the setup form, and a substring match that happens to be unique today would break the moment the two forms share a page.

Then replace `await page.goto('/')` with `await signIn(page)` in all four tests. In the `javascript:` URL test, the `page.route(...)` call must stay **before** `signIn(page)`, since the route interception has to be registered before any navigation.

- [ ] **Step 3: Create `web/tests/auth.spec.js`**

```js
import { expect, test } from '@playwright/test'

const EMAIL = 'e2e-admin@example.test'
const PASSWORD = 'e2e-password-1234'

test('an anonymous visit shows the login form, not the feed', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('.auth')).toBeVisible()
  await expect(page.locator('.item-row')).toHaveCount(0)
})

test('a wrong password is rejected with one generic message', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Password', { exact: true }).fill('definitely-not-it')
  await page.getByRole('button', { name: 'Sign in' }).click()

  await expect(page.locator('.auth .error')).toHaveText('Email or password is incorrect.')
  await expect(page.locator('.item-row')).toHaveCount(0)
})

test('an unknown email gives the same message as a wrong password', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Email').fill('nobody@example.test')
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()

  await expect(page.locator('.auth .error')).toHaveText('Email or password is incorrect.')
})

test('signing in and out round-trips', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()

  await expect(page.locator('.item-row')).toHaveCount(12)
  await expect(page.locator('.whoami')).toContainText('E2E Admin')
  await expect(page.locator('.badge')).toHaveText('admin')

  await page.getByRole('button', { name: 'sign out' }).click()
  await expect(page.locator('.auth')).toBeVisible()
})

test('the session survives a reload without a login flash', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.locator('.item-row')).toHaveCount(12)

  await page.reload()
  await expect(page.locator('.item-row')).toHaveCount(12)
  await expect(page.locator('.auth')).toHaveCount(0)
})

test('an invalid setup token is reported, not silently accepted', async ({ page }) => {
  await page.goto('/#setup=this-token-was-never-issued')

  await expect(page.locator('.auth h1')).toHaveText('Choose a password')
  await page.getByLabel('Password', { exact: true }).fill('a-good-password')
  await page.getByLabel('Confirm password').fill('a-good-password')
  await page.getByRole('button', { name: 'Create account' }).click()

  await expect(page.locator('.auth .error')).toContainText('invalid, expired, or already used')
})

test('mismatched setup passwords are caught before the request', async ({ page }) => {
  await page.goto('/#setup=whatever')

  await page.getByLabel('Password', { exact: true }).fill('a-good-password')
  await page.getByLabel('Confirm password').fill('a-different-password')
  await page.getByRole('button', { name: 'Create account' }).click()

  await expect(page.locator('.auth .error')).toHaveText('The two passwords do not match.')
})

test('subscribing from the strip filters a subscribed-only search', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.locator('.item-row')).toHaveCount(12)

  // With nothing subscribed, a subscribed-only search returns nothing.
  await page.getByLabel('subscribed only').check()
  await page.getByLabel('search').fill('collecting')
  await page.getByLabel('search').press('Enter')
  await expect(page.locator('.item-list .empty')).toBeVisible()

  // Subscribe to the one seeded source, then re-run the same search.
  await page.locator('.subs-summary').click()
  await page.locator('.subs-list input[type="checkbox"]').first().check()
  await page.getByLabel('search').press('Enter')
  await expect(page.locator('.item-row')).toHaveCount(12)
})
```

That last test is the one that proves the whole slice hangs together: a subscription written through `PUT /api/subscriptions/{id}` changes what `query.search`'s long-dormant `subscribed_only` join returns, visible in the browser.

- [ ] **Step 4: Check the webServer readiness probe**

`web/playwright.config.js` waits on `http://127.0.0.1:8000/api/sources`, which now returns 401 to the unauthenticated probe. Playwright documents 401 and 403 as acceptable readiness responses alongside 2xx and 3xx, so this should still work — but verify rather than assume. Add a comment recording it:

```js
      url: 'http://127.0.0.1:8000/api/sources',
      // Returns 401 now that every endpoint requires a session. Playwright
      // treats 401/403 as "the server is up", which is the only thing this
      // probe needs to establish.
```

**If the suite hangs waiting for the web server**, that assumption is wrong. In that case change the probe to `http://127.0.0.1:8000/api/docs`, which is unauthenticated FastAPI-served HTML, and note the change in your report.

- [ ] **Step 5: Run the e2e suite**

```bash
cd /Users/dev2/Desktop/Testing
.venv/bin/python web/tests/seed_e2e.py
cd web && npm run test:e2e
```

Expected: PASS, 12 tests (4 existing smoke tests plus 8 here).

**Ports:** the config uses 8000 and 5173. If either is occupied by a process you did not start, override the ports for the run rather than freeing them — edit `playwright.config.js` and `vite.config.js` to a spare pair (8100/5273), run the suite, then `git checkout -- playwright.config.js vite.config.js` and confirm with `grep -rn 8100 .` that nothing is left behind. **Never kill a process you did not start.**

- [ ] **Step 6: Commit**

```bash
cd /Users/dev2/Desktop/Testing
git add web/tests web/playwright.config.js
git commit -m "test: e2e coverage for login, setup, and subscriptions"
```

---

### Task 12: Documentation

**Files:**
- Modify: `docs/architecture.md`, `src/reachstore/api/app.py`, `web/README.md`, `README.md`

**Interfaces:**
- Consumes: everything above
- Produces: no code behaviour change

- [ ] **Step 1: Correct the `assert_loopback` docstring**

`src/reachstore/api/app.py:17-23` currently reads *"There is no authentication in this slice, so the network boundary is the only access control there is."* That is no longer true, and the guard's justification has to change with it — or a future reader will conclude the guard is obsolete and remove it. Replace the docstring:

```python
    """Refuse to serve on a non-loopback interface.

    There is authentication now, but not transport security: the session
    cookie does not set `Secure` (there is no HTTPS on localhost, and setting
    it would stop the cookie being sent at all), there are no CSRF tokens, and
    there is no login rate limiting. On a loopback interface none of those
    matter. On any other interface all three do, and the cookie would travel
    in cleartext.

    So the guard stays, and exposing this beyond localhost requires building
    HTTPS, CSRF tokens, and login rate limiting first -- not just flipping
    REACHSTORE_ALLOW_NONLOCAL.
    """
```

Also update the `RuntimeError` message, which repeats the stale claim:

```python
    raise RuntimeError(
        f"refusing to bind non-loopback host {host!r}: the session cookie is not "
        "Secure and there is no CSRF protection or login rate limiting. "
        "Set REACHSTORE_ALLOW_NONLOCAL=1 to override deliberately."
    )
```

Run `.venv/bin/pytest tests/test_api_app.py -v` afterwards. It should pass **unchanged**: `test_non_loopback_host_is_refused` asserts only that `"REACHSTORE_ALLOW_NONLOCAL"` appears in the message, and the replacement text above still contains it. If that test fails, your replacement dropped the override name — restore it rather than weakening the assertion.

- [ ] **Step 2: Update `docs/architecture.md`**

Four sections need edits. Keep the existing voice — short declarative sentences, reasons rather than restatements.

**§3 Invariants** — add:

```markdown
- **Every endpoint requires a session.** There is no anonymous read. The two
  exceptions are `POST /api/auth/login` and `POST /api/auth/setup`, which are
  how a request acquires a session in the first place.
- **Each table has exactly one owning module.** Content tables (`items`,
  `sources`, `fetch_runs`, `item_tags`) belong to `store.py` for writes and
  `query.py` for reads. The three auth tables (`users`, `sessions`, `invites`)
  belong to `api/auth.py`. `routes.py` builds no queries.
- **Accounts are created from a shell, never over HTTP from nothing.** There
  is no signup endpoint. `reachstore invite` issues a one-time link; only
  someone with shell access to this machine can start an account.
```

**§4 Data model** — add the two new tables and the new column:

```markdown
`users.is_admin` — one boolean, not a roles table. There are exactly two
levels: read the store, and operate it. A role system would be three tables
and a join to express what a boolean already says.

`sessions` — one row per logged-in browser. Only the SHA-256 of the cookie
value is stored, so a database dump yields no usable sessions. Rows rather
than signed stateless tokens, because `reachstore revoke-sessions` has to
take effect on the next request; a signed cookie could not be withdrawn
before it expired.

`invites` — pending accounts, separate from `users` so that a `users` row
always denotes a usable account rather than "an account, unless it is a
pending one". Consumed by setting `consumed_at`, which is what makes a link
single-use.
```

**§7 Web layer** — replace the description of the request path:

```markdown
A request carries a `reachstore_session` cookie. `api/auth.py` is the only
place that turns it into a `User`: `get_current_user` (401 if the cookie is
absent, unknown, or expired) and `require_admin` (403 unless `is_admin`).
Every route declares one of the two as a dependency. There is no middleware
doing this — a dependency is visible in the signature, so an endpoint added
without one is obvious at review.

The frontend has no router. `App.jsx` asks `/api/auth/me` on mount and
renders one of three things: the login form, the setup form (when the URL
carries a `#setup=<token>` fragment), or the store. The whole authenticated
UI lives in `Store.jsx` so that its hooks — which fetch on mount — cannot run
before there is a session.

Subscriptions filter reading, never collection. Collection stays tier-driven,
so unsubscribing hides a source from your view without stopping it being
collected and without affecting anyone else. Filtering at read time is
reversible; filtering at ingest is not — the same ELT reasoning that governs
item storage.
```

**§9 Decisions worth knowing** — add:

```markdown
- **scrypt from the stdlib, not bcrypt or argon2.** `hashlib.scrypt` is in
  Python 3.12 with no dependency to add. Measured at 41 ms with
  `n=2**15, r=8, p=1`: slow enough that offline brute force is expensive,
  fast enough that a login feels instant.
- **The session cookie is deliberately not `Secure`.** There is no HTTPS on
  localhost, and `Secure` would stop the cookie being sent at all. Together
  with the absent CSRF tokens and login rate limiting, this is why
  `assert_loopback` still exists: exposing this beyond localhost means
  building all three first, not flipping the override.
- **Login answers a wrong password and an unknown email identically**, and
  spends a full password verification on the unknown-email branch. Without
  that, response latency alone would reveal which addresses have accounts.
- **The setup link is a URL fragment (`/#setup=<token>`), not a query
  string.** A fragment never reaches the server, so a single-use credential
  stays out of access logs, proxy logs, and the `Referer` header. The path
  stays `/` in either form, which is the part that matters for serving: a real
  `/setup` path would 404 in production, because `StaticFiles(html=True)`
  looks for `404.html` rather than falling back to `index.html`.
- **Unsubscribing clears `subscriptions.active` rather than deleting the
  row.** The row carries `label`, reserved for per-user renaming, which a
  delete would destroy. That choice is why `subscribe` uses `ON CONFLICT DO
  UPDATE` to reactivate rather than `DO NOTHING`.
```

**Also delete every remaining reference to `DEFAULT_USER_ID`** in this file — it no longer exists.

- [ ] **Step 3: Update the READMEs**

In the root `README.md`, add a section after the setup instructions:

```markdown
## Accounts

There is no signup page. An account starts with a shell command:

```bash
.venv/bin/python -m reachstore.cli invite someone@example.com --name "Someone"
.venv/bin/python -m reachstore.cli invite boss@example.com --name "Boss" --admin
```

Each prints a one-time setup link, valid 7 days, that the person opens to
choose a password. `WEB_BASE_URL` in `.env` controls the host and port the
link is built against — 5173 for the Vite dev server, 8000 when FastAPI
serves the built frontend.

Two other commands:

```bash
.venv/bin/python -m reachstore.cli set-password someone@example.com
.venv/bin/python -m reachstore.cli revoke-sessions someone@example.com
```

Note on migrations: Alembic does not read `.env` — `migrations/env.py` takes
the URL from the real environment. Export it first:

```bash
export $(grep -E '^DATABASE_URL=' .env | xargs)
.venv/bin/alembic upgrade head
```

The CLI and the API do not need this; they load `.env` through pydantic
`Settings`.

`--admin` grants the operator surface: the health strip, and the Collect
button. Everyone else can read, search, and subscribe.
```

In `web/README.md`, note in the e2e section that the specs sign in first, using the admin account `seed_e2e.py` creates, and that the credentials are duplicated in both files and must stay in step.

- [ ] **Step 4: Run everything**

```bash
cd /Users/dev2/Desktop/Testing
.venv/bin/pytest
.venv/bin/python web/tests/seed_e2e.py
cd web && npm run build && npm run test:e2e
```

Expected: the Python suite green with zero warnings, the build clean, and 12 e2e tests passing.

- [ ] **Step 5: Final consistency sweep**

```bash
cd /Users/dev2/Desktop/Testing
grep -rn "DEFAULT_USER_ID" src/ web/src/ docs/architecture.md || echo "clean"
grep -rn "no authentication" src/ docs/architecture.md || echo "clean"
git status --porcelain
git check-ignore .env && echo ".env is ignored"
```

Both greps must come back clean.

**Scope note — this is important.** The greps are deliberately limited to `src/`, `web/src/`, and `docs/architecture.md`. **Do not touch `docs/superpowers/specs/`, `docs/superpowers/plans/`, or `docs/superpowers/reviews/`.** Those are the preserved historical record of earlier slices (committed deliberately in `f978ec2`, "docs: preserve execution ledger and per-task reports"). Plan 1's spec and plan correctly describe `DEFAULT_USER_ID` and "no authentication" as facts *of their time*; editing them to match today would falsify the record of how this system got here. `docs/architecture.md` is the only living document that must reflect current reality.

The last command confirms `.env` — which holds `WEB_BASE_URL` and the database URLs — is still untracked.

- [ ] **Step 6: Commit**

```bash
git add docs/architecture.md README.md web/README.md src/reachstore/api/app.py
git commit -m "docs: auth, subscriptions, and why the loopback guard stays"
```

---

## Known deviations from the spec

Recorded here so a reviewer does not treat them as implementation drift. Both were found while writing this plan.

1. **Setup link is `/#setup=<token>`; the spec said `/?setup=<token>`.** Both keep the path at `/`, so neither 404s under `StaticFiles` — the spec was right about that. The fragment is preferred solely because it is never sent to the server, keeping a single-use credential out of access logs, proxy logs, and the `Referer` header. Task 9, Step 5.

2. **`GET /api/subscriptions` was dropped, and `/api/catalog` absorbed its job.** The spec had catalog return `{source_id, kind, identifier}` and a separate endpoint return `{source_id, label, active}`. This plan has catalog return `{source_id, kind, identifier, tier, subscribed}` and drops the second endpoint: one request instead of two, and a `subscribed` flag that cannot drift from the row it describes. `tier` is added because the strip shows it; it is a collection-frequency class, not a credential, so §7.1's reasoning about identifiers is unaffected. `subscriptions.label` stays unexposed, as the spec intended. Task 8.

3. **Subscribe uses `ON CONFLICT DO UPDATE SET active = true`, not `DO NOTHING`.** The spec specified `DO NOTHING`, which is incompatible with the unsubscribe this plan implements: since unsubscribe clears `active` rather than deleting the row, `DO NOTHING` would make re-subscribing a silent no-op that leaves the user unsubscribed. Soft-delete is the right half to keep, because the row carries `label` — reserved by the spec's §8 for per-user renaming — which a hard delete would destroy. `test_resubscribing_after_unsubscribing_works` pins the behaviour. Task 8.

4. **`POST /api/auth/setup` returns 409 for an email that already has an account** — following the spec, and deliberately *not* folded into the uniform 400 used for every token failure. Whoever holds the token already knows the email it names, so the distinction leaks nothing they did not supply. Task 7.

5. **The Plan-2 constraint "all SQL lives in `store.py` and `query.py`" is restated** as one owning module per table, because `auth.py` must query `sessions` and `invites`. See the amendment in Global Constraints. `post_login` and the three CLI commands also read `users` directly; consolidating those four into an `auth.find_user_by_email` helper is noted as optional in Tasks 4 and 6.
