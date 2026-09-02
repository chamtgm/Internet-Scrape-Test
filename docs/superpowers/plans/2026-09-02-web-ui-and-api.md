# Web UI and JSON API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `reachstore` a browser interface — a FastAPI layer over the existing store and a React two-pane reader that browses, searches, reads, and triggers collection with live progress.

**Architecture:** A thin FastAPI app (`src/reachstore/api/`) that calls existing `query` and `collect` functions and serialises their results — it builds no SQL of its own. A React + Vite frontend (`web/`) served by Vite in development (proxying `/api` to FastAPI) and by FastAPI from `web/dist` in production. Collection runs as a FastAPI background task; the client polls `GET /api/sources`, which reports both per-source progress and whether a run is still in flight.

**Tech Stack:** FastAPI, Uvicorn, Pydantic v2, SQLAlchemy 2.x (existing), React 18, Vite 5, Playwright (already installed).

**Spec:** `docs/superpowers/specs/2026-08-31-web-ui-and-api-design.md`

## Global Constraints

- Python 3.11 or newer. Type hints on all public functions.
- PostgreSQL 16. No SQLite fallback.
- **No network access in tests.** Every external call goes through an injected dependency; tests supply fakes backed by committed fixture files.
- **Only entrypoints read the real clock — `cli.py` and the `api/` package. Never `query`, `collect`, `store`, or any adapter.** (Widened from Plan 1's "only `cli.py`"; `docs/architecture.md` §3 already anticipates this.)
- All SQL lives in `store.py` and `query.py`. **The API must not import `sqlalchemy.select` or build any query.** ORM object construction plus `session.add` is permitted in entrypoints and is not a violation.
- Tenant isolation predicate: `items.owner_user_id IS NULL OR items.owner_user_id = :user_id`, in exactly one function — `query.visible_to`. The API passes `user_id` down and must never filter by owner itself.
- Every collection operation must be idempotent.
- Free tooling only. No paid services, no API keys.
- Timestamps are timezone-aware UTC (`TIMESTAMPTZ`).
- **No CORS middleware anywhere.** Vite proxies in dev, FastAPI serves the build in production — same-origin both times.
- **The server must refuse to bind a non-loopback host** unless `REACHSTORE_ALLOW_NONLOCAL=1`.

## Existing code this plan builds on

Verified against the tree at branch `feat/web-ui-and-api`. Do not re-derive these from memory:

```python
# src/reachstore/db.py
make_engine(url: str) -> Engine
make_session_factory(engine: Engine) -> sessionmaker[Session]        # expire_on_commit=False

# src/reachstore/config.py
get_settings() -> Settings                                            # .database_url, .raw_dir: Path

# src/reachstore/query.py
feed(session, *, user_id, limit=50, before_id=None, before_published_at=None) -> list[Item]
search(session, *, user_id, q, kinds=None, since=None, subscribed_only=False, limit=50) -> list[Item]
get_item(session, *, user_id, item_id) -> Item | None
source_health(session) -> list[SourceStatus]                          # no user_id
MAX_LIMIT = 200

# src/reachstore/collect.py
collect_tier(session, *, tier, registry, raw_dir, now, force=False) -> list[CollectResult]

# src/reachstore/adapters/registry.py
build_registry(http: HttpFetcher, runner: CommandRunner) -> dict[str, Adapter]

# src/reachstore/adapters/base.py
HttpxFetcher(), SubprocessRunner()
NormalizedItem(external_id, url, content_text, title=None, author_handle=None, published_at=None, raw={})
```

Test helpers that already exist — **use these, do not invent new ones:**

```python
# tests/conftest.py
session      # function-scoped; join_transaction_mode="create_savepoint" (see Task 4)
raw_dir      # tmp_path / "raw"

# tests/test_collect.py
NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
StubAdapter(kind: str, items=None, error: Exception | None = None)    # kind is positional
add_source(session, kind="rss", identifier="https://a/feed", tier=1) -> Source
one_item() -> list[NormalizedItem]

# tests/test_query_isolation.py
setup_two_users_with_private_items(session, raw_dir) -> (alice, bob)
```

## File Structure

```
pyproject.toml                        Modify: add fastapi, uvicorn

src/reachstore/models.py              Modify: Item.source relationship
src/reachstore/query.py               Modify: selectinload; SourceStatus.error_text, .item_count
src/reachstore/collect.py             Modify: per-source commit in collect_tier

src/reachstore/api/__init__.py        Empty
src/reachstore/api/deps.py            Process-wide engine, get_session(), DEFAULT_USER_ID
src/reachstore/api/schemas.py         Pydantic response models
src/reachstore/api/routes.py          Endpoint handlers
src/reachstore/api/app.py             FastAPI app, loopback guard, static mount
src/reachstore/api/collect_runner.py  Background collection task + concurrency flag

web/package.json                      React + Vite deps
web/vite.config.js                    Dev proxy /api -> 127.0.0.1:8000
web/index.html                        Vite entry
web/src/main.jsx                      React root
web/src/App.jsx                       Two-pane shell, polling loop
web/src/api.js                        fetch wrappers, one per endpoint
web/src/components/SearchBar.jsx      Query input + tier select + Collect button
web/src/components/HealthStrip.jsx    Source summary, expands to full list
web/src/components/ItemList.jsx       Left pane; paginated on the compound cursor
web/src/components/ItemDetail.jsx     Right pane; full stored text
web/src/styles.css                    All styling; no CSS framework

tests/test_api_sources.py             Health endpoint
tests/test_api_read.py                feed / search / items
tests/test_api_collect.py             Collect endpoint + concurrency guard
tests/test_api_app.py                 Loopback guard
tests/test_collect_commits.py         Per-source commit behaviour
web/tests/seed_e2e.py                 Deterministic e2e data for the test database
web/tests/smoke.spec.js               Playwright smoke test
```

**Responsibility boundaries:** `deps.py` owns connections and identity. `schemas.py` owns wire shapes. `routes.py` translates HTTP to `query`/`collect` calls. `collect_runner.py` owns the background task and its guard. No file writes SQL except `query.py` and `store.py`.

---

### Task 1: Store-layer prerequisites

**Files:**
- Modify: `src/reachstore/models.py`, `src/reachstore/query.py`
- Test: `tests/test_query_isolation.py` (append), `tests/test_collect.py` (append)

**Interfaces:**
- Consumes: nothing new
- Produces:
  - `Item.source` — `Mapped[Source]`, eagerly loaded by `feed`, `search`, `get_item`
  - `query.SourceStatus` gains `error_text: str | None` and `item_count: int`

The API needs each item's source name for the list rows, and the health strip needs the failure reason. Both are one join away but neither is reachable today: `Item` has no relationship to `Source`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_query_isolation.py`:

```python
def test_feed_items_expose_their_source(session, raw_dir):
    alice, _bob = setup_two_users_with_private_items(session, raw_dir)
    items = feed(session, user_id=alice.id)
    assert items, "expected seeded items"
    for item in items:
        assert item.source.identifier


def test_get_item_exposes_its_source(session, raw_dir):
    alice, _bob = setup_two_users_with_private_items(session, raw_dir)
    first = feed(session, user_id=alice.id)[0]
    fetched = get_item(session, user_id=alice.id, item_id=first.id)
    assert fetched is not None
    assert fetched.source.identifier == first.source.identifier


def test_search_items_expose_their_source(session, raw_dir):
    alice, _bob = setup_two_users_with_private_items(session, raw_dir)
    results = search(session, user_id=alice.id, q="body")
    assert results, "expected search hits"
    for item in results:
        assert item.source.identifier
```

If `q="body"` returns nothing, open `setup_two_users_with_private_items` and pick a word that actually appears in its `content_text`. Do not weaken the assertion to `assert True`.

Append to `tests/test_collect.py`:

```python
def test_source_health_reports_error_text_and_item_count(session, raw_dir):
    good = add_source(session, kind="rss", identifier="https://a/feed", tier=1)
    bad = add_source(session, kind="web_page", identifier="https://b", tier=1)
    registry = {
        "rss": StubAdapter("rss", items=one_item()),
        "web_page": StubAdapter("web_page", error=AdapterError("upstream exploded")),
    }
    collect_tier(session, tier=1, registry=registry, raw_dir=raw_dir, now=NOW)

    health = {s.source_id: s for s in source_health(session)}
    assert health[good.id].item_count == 1
    assert health[good.id].error_text is None
    assert health[bad.id].item_count == 0
    assert "upstream exploded" in health[bad.id].error_text
```

`AdapterError`, `StubAdapter`, `add_source`, `one_item`, `collect_tier`, `source_health`, and `NOW` are all already imported at the top of `tests/test_collect.py`. Add no imports.

Note for Task 4, which imports *from* this file: there is no `tests/__init__.py` and no `pythonpath` setting, so pytest puts `tests/` itself on `sys.path` and the module is importable only as `test_collect`, not `tests.test_collect`. Verified — the dotted form raises `ModuleNotFoundError: No module named 'tests'`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_query_isolation.py -k source tests/test_collect.py -k error_text -v`
Expected: FAIL — `AttributeError: 'Item' object has no attribute 'source'`, and `AttributeError: 'SourceStatus' object has no attribute 'item_count'`.

- [ ] **Step 3: Add the relationship to `models.py`**

Change the `sqlalchemy.orm` import line to:

```python
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
```

Add to `class Item`, after the `content_hash` column:

```python
    source: Mapped["Source"] = relationship(lazy="raise")
```

`lazy="raise"` makes an un-eagerly-loaded access raise immediately instead of silently emitting one query per row. That turns an N+1 into a loud test failure rather than a slow endpoint in production. Nothing reads `item.source` today, so this cannot break existing code.

- [ ] **Step 4: Eagerly load the relationship in `query.py`**

Change the `sqlalchemy.orm` import line to:

```python
from sqlalchemy.orm import Session, selectinload
```

Add `.options(selectinload(Item.source))` to the statement in all three read functions. In `get_item`:

```python
    stmt = (
        select(Item)
        .options(selectinload(Item.source))
        .where(Item.id == item_id, visible_to(user_id))
    )
```

In `feed`, change `stmt = select(Item).where(visible_to(user_id))` to:

```python
    stmt = select(Item).options(selectinload(Item.source)).where(visible_to(user_id))
```

In `search`, change `stmt = select(Item)` to:

```python
    stmt = select(Item).options(selectinload(Item.source))
```

`search` conditionally `.join(Source, ...)` a few lines later for the `kinds` filter. That join and `selectinload` coexist — `selectinload` issues its own second SELECT for the sources and does not interfere with the join used for filtering. Do not try to replace one with the other.

Change no `where`, `order_by`, or `limit` clause.

- [ ] **Step 5: Extend `SourceStatus` and `source_health`**

In `query.py`, add two fields to the dataclass:

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
    error_text: str | None
    item_count: int
```

In `source_health`, after `sources = session.execute(...)` and before the loop, count items for every source in one query rather than one per source:

```python
    counts = dict(
        session.execute(
            select(Item.source_id, func.count(Item.id)).group_by(Item.source_id)
        ).all()
    )
```

`func` and `select` are already imported in `query.py`. Then add two keyword arguments to the `SourceStatus(...)` construction inside the loop:

```python
                error_text=last.error_text if last else None,
                item_count=counts.get(source.id, 0),
```

A source that has never collected has no row in `counts`, hence the `0` default rather than a `KeyError`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_query_isolation.py tests/test_collect.py -v`
Expected: PASS.

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/pytest`
Expected: PASS, 90 tests. If `lazy="raise"` surfaces a lazy access somewhere unexpected, add `selectinload` at that call site — do not weaken the relationship to `lazy="select"`.

- [ ] **Step 8: Commit**

```bash
git add src/reachstore/models.py src/reachstore/query.py tests/test_query_isolation.py tests/test_collect.py
git commit -m "feat: expose Item.source and add error_text/item_count to SourceStatus"
```

---

### Task 2: API foundation and the health endpoint

**Files:**
- Modify: `pyproject.toml`
- Create: `src/reachstore/api/__init__.py`, `deps.py`, `schemas.py`, `routes.py`, `app.py`
- Test: `tests/test_api_sources.py`, `tests/test_api_app.py`

**Interfaces:**
- Consumes: `query.source_health(session) -> list[SourceStatus]` (Task 1)
- Produces:
  - `api.deps.get_session()` — FastAPI dependency yielding a `Session`
  - `api.deps.get_session_factory() -> sessionmaker[Session]`
  - `api.deps.raw_dir() -> Path`
  - `api.deps.DEFAULT_USER_ID: int = 1`
  - `api.app.create_app() -> FastAPI`, `api.app.assert_loopback(host, *, allow_nonlocal)`
  - `GET /api/sources`

- [ ] **Step 1: Add dependencies**

In `pyproject.toml`, add to the `dependencies` list:

```toml
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
```

Then install:

```bash
uv pip install --python .venv/bin/python -e ".[dev]"
```

`httpx` is already a dependency (the adapters use it) and is what `fastapi.testclient.TestClient` needs, so no separate test dependency is required.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_api_sources.py`:

```python
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from reachstore.api.app import create_app
from reachstore.api.deps import get_session
from reachstore.models import Source

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def make_client(session):
    """A TestClient whose session is the test's rolled-back fixture session.

    dependency_overrides is how the app gets a session it did not open. Without
    it every test would hit the real database_url from .env.
    """
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


def test_sources_endpoint_returns_every_source(session):
    session.add(
        Source(kind="rss", identifier="https://a/feed", tier=1, config_json={}, created_at=NOW)
    )
    session.flush()

    body = make_client(session).get("/api/sources").json()
    assert [s["identifier"] for s in body["sources"]] == ["https://a/feed"]
    assert body["sources"][0]["kind"] == "rss"
    assert body["sources"][0]["item_count"] == 0
    assert body["sources"][0]["last_status"] is None
    assert body["sources"][0]["error_text"] is None


def test_sources_endpoint_is_empty_when_no_sources(session):
    assert make_client(session).get("/api/sources").json()["sources"] == []
```

Assert on the `sources` key rather than whole-response equality: Task 5 adds a `collecting` field to this response, and a `== {"sources": []}` assertion would then fail for no good reason.

Create `tests/test_api_app.py`:

```python
import pytest

from reachstore.api.app import assert_loopback


def test_loopback_hosts_are_allowed():
    for host in ("127.0.0.1", "localhost", "::1"):
        assert_loopback(host, allow_nonlocal=False)


def test_non_loopback_host_is_refused():
    with pytest.raises(RuntimeError) as exc:
        assert_loopback("0.0.0.0", allow_nonlocal=False)
    assert "REACHSTORE_ALLOW_NONLOCAL" in str(exc.value)


def test_non_loopback_host_allowed_with_explicit_override():
    assert_loopback("0.0.0.0", allow_nonlocal=True)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_api_sources.py tests/test_api_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reachstore.api'`.

- [ ] **Step 4: Create `src/reachstore/api/__init__.py`**

Empty file.

- [ ] **Step 5: Create `src/reachstore/api/deps.py`**

```python
from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from reachstore.config import get_settings
from reachstore.db import make_engine, make_session_factory

DEFAULT_USER_ID = 1
"""The single user this slice serves.

There is no authentication yet. Every route passes this to the `query`
functions exactly where Plan 2 will pass the authenticated user's id, so the
tenant-isolation path stays live and exercised rather than stubbed out. Plan 2
replaces a constant instead of threading a new parameter through every call
site.
"""


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
```

- [ ] **Step 6: Create `src/reachstore/api/schemas.py`**

```python
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SourceStatusOut(BaseModel):
    source_id: int
    kind: str
    identifier: str
    last_status: str | None
    last_run_at: datetime | None
    consecutive_failures: int
    needs_attention: bool
    error_text: str | None
    item_count: int


class SourcesResponse(BaseModel):
    sources: list[SourceStatusOut]
```

- [ ] **Step 7: Create `src/reachstore/api/routes.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from reachstore import query
from reachstore.api.deps import get_session
from reachstore.api.schemas import SourcesResponse, SourceStatusOut

router = APIRouter(prefix="/api")


@router.get("/sources", response_model=SourcesResponse)
def list_sources(session: Session = Depends(get_session)) -> SourcesResponse:
    statuses = query.source_health(session)
    return SourcesResponse(sources=[SourceStatusOut(**vars(s)) for s in statuses])
```

`vars(s)` works because `SourceStatus` is a plain frozen dataclass whose field names match `SourceStatusOut` exactly. If a field is added to one and not the other, Pydantic raises at construction instead of silently dropping it.

- [ ] **Step 8: Create `src/reachstore/api/app.py`**

```python
from __future__ import annotations

import ipaddress
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from reachstore.api.routes import router

# app.py -> api -> reachstore -> src -> repo root
WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"


def assert_loopback(host: str, *, allow_nonlocal: bool) -> None:
    """Refuse to serve on a non-loopback interface.

    There is no authentication in this slice, so the network boundary is the
    only access control there is. Binding 0.0.0.0 on an untrusted network
    exposes the entire store, including private items, to anyone who can reach
    the port.
    """
    if allow_nonlocal:
        return
    if host == "localhost":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise RuntimeError(
        f"refusing to bind non-loopback host {host!r}: there is no authentication. "
        "Set REACHSTORE_ALLOW_NONLOCAL=1 to override deliberately."
    )


def create_app() -> FastAPI:
    app = FastAPI(title="reachstore", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.include_router(router)
    # Mounted last and only if built, so /api/* always wins the route match and
    # the API is fully usable before any frontend exists.
    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
    return app


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    assert_loopback(host, allow_nonlocal=os.environ.get("REACHSTORE_ALLOW_NONLOCAL") == "1")
    uvicorn.run(create_app(), host=host, port=port)
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_api_sources.py tests/test_api_app.py -v`
Expected: PASS (5 passed).

- [ ] **Step 10: Verify against the real database**

```bash
.venv/bin/python -c "from reachstore.api.app import serve; serve()" &
sleep 3
curl -s localhost:8000/api/sources | head -c 500; echo
kill %1
```

Expected: JSON listing the real sources with their true `item_count` values.

- [ ] **Step 11: Commit**

```bash
git add pyproject.toml src/reachstore/api tests/test_api_sources.py tests/test_api_app.py
git commit -m "feat: FastAPI foundation, loopback guard, and the sources endpoint"
```

---

### Task 3: Read endpoints

**Files:**
- Modify: `src/reachstore/api/schemas.py`, `src/reachstore/api/routes.py`
- Test: `tests/test_api_read.py`

**Interfaces:**
- Consumes: `query.feed`, `query.search`, `query.get_item` (signatures in "Existing code" above)
- Produces: `GET /api/feed`, `GET /api/search`, `GET /api/items/{item_id}`; schemas `ItemSummary`, `ItemDetail`, `Cursor`, `FeedResponse`, `SearchResponse`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_read.py`:

```python
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from reachstore.adapters.base import NormalizedItem
from reachstore.api.app import create_app
from reachstore.api.deps import get_session
from reachstore.models import Source
from reachstore.store import upsert_items

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def make_client(session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


def seed(session, raw_dir, count=5):
    source = Source(
        kind="rss", identifier="https://a/feed", tier=1, config_json={}, created_at=NOW
    )
    session.add(source)
    session.flush()
    items = [
        NormalizedItem(
            external_id=f"e{i}",
            url=f"https://a/{i}",
            title=f"Item {i}",
            content_text=f"body number {i} " + "padding " * 60,
            published_at=NOW - timedelta(days=i),
        )
        for i in range(count)
    ]
    upsert_items(
        session,
        source_id=source.id,
        items=items,
        owner_user_id=None,
        raw_dir=raw_dir,
        now=NOW,
    )
    return source


def test_feed_returns_items_newest_first_with_source_labels(session, raw_dir):
    seed(session, raw_dir)
    body = make_client(session).get("/api/feed").json()
    assert [i["title"] for i in body["items"]] == [f"Item {i}" for i in range(5)]
    assert body["items"][0]["source_kind"] == "rss"
    assert body["items"][0]["source_identifier"] == "https://a/feed"


def test_feed_excerpt_is_truncated_and_detail_is_not(session, raw_dir):
    seed(session, raw_dir)
    client = make_client(session)
    summary = client.get("/api/feed").json()["items"][0]
    assert len(summary["excerpt"]) <= 240
    detail = client.get(f"/api/items/{summary['id']}").json()
    assert len(detail["content_text"]) > 240
    assert detail["content_text"].startswith("body number 0")
    assert detail["fetched_at"]


def test_feed_paginates_without_gaps_or_duplicates(session, raw_dir):
    seed(session, raw_dir, count=5)
    client = make_client(session)
    seen, cursor, pages = [], None, 0
    while pages < 10:
        params = {"limit": 2}
        if cursor is not None:
            params["before_id"] = cursor["id"]
            # Omitted entirely when null -- that is the NULLS LAST tail cursor.
            if cursor["published_at"] is not None:
                params["before_published_at"] = cursor["published_at"]
        body = client.get("/api/feed", params=params).json()
        seen.extend(i["id"] for i in body["items"])
        cursor = body["next_cursor"]
        pages += 1
        if cursor is None:
            break
    assert len(seen) == 5
    assert len(set(seen)) == 5


def test_search_ranks_and_filters_by_kind(session, raw_dir):
    seed(session, raw_dir)
    client = make_client(session)
    assert client.get("/api/search", params={"q": "padding"}).json()["items"]
    narrowed = client.get("/api/search", params={"q": "padding", "kind": "github_repo"}).json()
    assert narrowed["items"] == []


def test_search_results_carry_source_labels(session, raw_dir):
    seed(session, raw_dir)
    hits = make_client(session).get("/api/search", params={"q": "padding"}).json()["items"]
    assert hits[0]["source_identifier"] == "https://a/feed"


def test_missing_item_is_404(session, raw_dir):
    seed(session, raw_dir)
    assert make_client(session).get("/api/items/999999").status_code == 404


def test_bad_limit_is_422(session, raw_dir):
    seed(session, raw_dir)
    client = make_client(session)
    assert client.get("/api/feed", params={"limit": "banana"}).status_code == 422
    assert client.get("/api/feed", params={"limit": 0}).status_code == 422
    assert client.get("/api/search", params={"q": ""}).status_code == 422
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_api_read.py -v`
Expected: FAIL — 404 on `/api/feed`, because the routes do not exist yet.

- [ ] **Step 3: Add the response models to `schemas.py`**

```python
class ItemSummary(BaseModel):
    id: int
    title: str | None
    url: str
    author_handle: str | None
    published_at: datetime | None
    source_id: int
    source_kind: str
    source_identifier: str
    excerpt: str


class ItemDetail(ItemSummary):
    content_text: str
    fetched_at: datetime


class Cursor(BaseModel):
    published_at: datetime | None
    id: int


class FeedResponse(BaseModel):
    items: list[ItemSummary]
    next_cursor: Cursor | None


class SearchResponse(BaseModel):
    items: list[ItemSummary]
```

- [ ] **Step 4: Add the routes**

Replace the import block at the top of `routes.py` with:

```python
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from reachstore import query
from reachstore.api.deps import DEFAULT_USER_ID, get_session
from reachstore.api.schemas import (
    Cursor,
    FeedResponse,
    ItemDetail,
    ItemSummary,
    SearchResponse,
    SourcesResponse,
    SourceStatusOut,
)
from reachstore.models import Item

router = APIRouter(prefix="/api")

EXCERPT_CHARS = 240
```

Then append the handlers:

```python
def _summary(item: Item) -> ItemSummary:
    return ItemSummary(
        id=item.id,
        title=item.title,
        url=item.url,
        author_handle=item.author_handle,
        published_at=item.published_at,
        source_id=item.source_id,
        source_kind=item.source.kind,
        source_identifier=item.source.identifier,
        # Collapse whitespace before truncating: stored text carries the
        # upstream's newlines and indentation, which would otherwise eat most
        # of the excerpt budget.
        excerpt=" ".join(item.content_text.split())[:EXCERPT_CHARS],
    )


@router.get("/feed", response_model=FeedResponse)
def get_feed(
    session: Session = Depends(get_session),
    limit: int = Query(50, ge=1, le=200),
    before_published_at: datetime | None = None,
    before_id: int | None = None,
) -> FeedResponse:
    """One page of the feed, newest first.

    `before_published_at` is absent rather than null when the previous page's
    last item had no published_at. That is not a missing value: `query.feed`
    reads (before_id set, before_published_at None) as "continue through the
    NULLS LAST tail", which is exactly the right meaning.
    """
    items = query.feed(
        session,
        user_id=DEFAULT_USER_ID,
        limit=limit,
        before_id=before_id,
        before_published_at=before_published_at,
    )
    # A short page means the end. Only a full page can have more behind it.
    cursor = None
    if len(items) == limit:
        last = items[-1]
        cursor = Cursor(published_at=last.published_at, id=last.id)
    return FeedResponse(items=[_summary(i) for i in items], next_cursor=cursor)


@router.get("/search", response_model=SearchResponse)
def get_search(
    q: str = Query(..., min_length=1),
    kind: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> SearchResponse:
    items = query.search(
        session,
        user_id=DEFAULT_USER_ID,
        q=q,
        kinds=[kind] if kind else None,
        limit=limit,
    )
    return SearchResponse(items=[_summary(i) for i in items])


@router.get("/items/{item_id}", response_model=ItemDetail)
def get_one_item(item_id: int, session: Session = Depends(get_session)) -> ItemDetail:
    """404 both when the item does not exist and when it is not visible.

    The two are deliberately indistinguishable, so this endpoint cannot be
    used to probe for the existence of another user's private items once
    Plan 2 introduces real users.
    """
    item = query.get_item(session, user_id=DEFAULT_USER_ID, item_id=item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    return ItemDetail(
        **_summary(item).model_dump(),
        content_text=item.content_text,
        fetched_at=item.fetched_at,
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_api_read.py -v`
Expected: PASS (7 passed).

- [ ] **Step 6: Run the full suite and commit**

```bash
.venv/bin/pytest
git add src/reachstore/api tests/test_api_read.py
git commit -m "feat: feed, search, and item detail endpoints"
```

---

### Task 4: Per-source commits in `collect_tier`

**Files:**
- Modify: `src/reachstore/collect.py`
- Test: `tests/test_collect_commits.py`

**Interfaces:**
- Consumes: `collect_source(session, *, source, adapter, raw_dir, now) -> CollectResult`
- Produces: `collect_tier` commits after each source. Signature unchanged.

This implements finding **I4** from the Plan 1 final review, deferred there as non-blocking for a CLI. It blocks the live progress view: `collect_tier` currently commits nowhere, so nothing is durable until the caller commits at the very end.

**Read this before writing the test.** `tests/conftest.py` creates the session with `join_transaction_mode="create_savepoint"`, so `session.commit()` inside a test commits a *savepoint*, not the outer transaction — a second connection can never observe it. Any test written around cross-connection visibility will fail for a reason unrelated to the change. Assert on the commit *ordering* instead, which is the actual behaviour being added.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_collect_commits.py`:

```python
import pytest
from sqlalchemy import select

from test_collect import NOW, StubAdapter, add_source, one_item

from reachstore.collect import collect_tier
from reachstore.models import FetchRun


def test_each_source_is_committed_before_the_next_one_starts(session, raw_dir, monkeypatch):
    """Commits must interleave with fetches, not all land at the end.

    This is what makes the UI's progress view progressive rather than a long
    pause followed by everything appearing at once.
    """
    add_source(session, kind="rss", identifier="https://a/feed", tier=1)
    add_source(session, kind="web_page", identifier="https://b", tier=1)

    events: list[str] = []
    real_commit = session.commit

    def spy_commit():
        events.append("commit")
        real_commit()

    monkeypatch.setattr(session, "commit", spy_commit)

    class RecordingAdapter:
        def __init__(self, kind):
            self.kind = kind
            self.tier = 1

        def fetch(self, identifier, since):
            events.append(f"fetch:{identifier}")
            return one_item()

    registry = {"rss": RecordingAdapter("rss"), "web_page": RecordingAdapter("web_page")}
    collect_tier(session, tier=1, registry=registry, raw_dir=raw_dir, now=NOW)

    assert events == [
        "fetch:https://a/feed",
        "commit",
        "fetch:https://b",
        "commit",
    ]


def test_a_failing_commit_does_not_abort_the_rest_of_the_tier(session, raw_dir, monkeypatch):
    """The bulkhead has to cover the commit too.

    `collect_source` never raises, but the commit that now follows it can --
    a dropped connection, a deadlock. Letting that escape would abort the
    whole tier, which is precisely what per-source isolation exists to stop.
    """
    add_source(session, kind="rss", identifier="https://a/feed", tier=1)
    add_source(session, kind="web_page", identifier="https://b", tier=1)
    add_source(session, kind="github_repo", identifier="o/r", tier=1)

    real_commit = session.commit
    attempts = {"n": 0}

    def flaky_commit():
        attempts["n"] += 1
        if attempts["n"] == 2:
            raise RuntimeError("connection lost")
        real_commit()

    monkeypatch.setattr(session, "commit", flaky_commit)

    registry = {
        "rss": StubAdapter("rss", items=one_item()),
        "web_page": StubAdapter("web_page", items=one_item()),
        "github_repo": StubAdapter("github_repo", items=one_item()),
    }
    results = collect_tier(session, tier=1, registry=registry, raw_dir=raw_dir, now=NOW)

    assert len(results) == 3, "a failed commit stopped the tier"
    assert attempts["n"] == 3


def test_a_crash_mid_source_leaves_no_committed_running_row(session, raw_dir):
    """A committed `running` row would silently reset the circuit breaker.

    `consecutive_failures` scans newest-first and stops at the first
    non-"failed" status, so a single stale `running` sitting on top of a long
    failure streak reports zero failures and reopens a source that has been
    broken for days. Per-source commit must never expose that state.

    KeyboardInterrupt is a BaseException, so `collect_source`'s `except
    Exception` bulkhead does not catch it -- it propagates exactly as a real
    Ctrl-C or process kill would, mid-source, after the "running" row was
    flushed but before it reached a terminal status.
    """
    add_source(session, kind="rss", identifier="https://a/feed", tier=1)

    class CrashingAdapter:
        kind = "rss"
        tier = 1

        def fetch(self, identifier, since):
            raise KeyboardInterrupt("simulated process death")

    with pytest.raises(KeyboardInterrupt):
        collect_tier(
            session,
            tier=1,
            registry={"rss": CrashingAdapter()},
            raw_dir=raw_dir,
            now=NOW,
        )

    # Discard the uncommitted work, exactly as a crashed process would.
    session.rollback()
    statuses = session.execute(select(FetchRun.status)).scalars().all()
    assert "running" not in statuses
```

The second test fails the *second* commit specifically: the first has already committed the `sources` rows, so the rollback that follows leaves them in place and the third source can still run.

The third test discharges the "stale `running` rows" risk recorded in the spec's risk table. It is the reason Task 5 exposes an explicit `collecting` flag: a `running` row is by design never visible to a reader, so it cannot serve as a completion signal.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_collect_commits.py -v`
Expected: the first two FAIL — the first showing fetches with no interleaved commits, the second with `RuntimeError: connection lost` escaping `collect_tier`. The third may already pass, since nothing is committed at all today; it is there to stay passing once commits are added.

- [ ] **Step 3: Commit after each source in `collect_tier`**

In `collect.py`, replace the loop body in `collect_tier`:

```python
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
        try:
            # Commit each source's terminal state before starting the next, so
            # a reader sees runs land one at a time and a crash mid-tier keeps
            # the failures the circuit breaker depends on.
            session.commit()
        except Exception:
            # The bulkhead extends to the commit. Letting a commit failure
            # escape would abort the whole tier -- the exact failure mode
            # per-source isolation exists to prevent. Roll back so the session
            # is usable for the next source; if the database is genuinely gone,
            # every remaining source records a failure and `collect` exits 1
            # through the existing all-sources-failed path.
            session.rollback()
    return results
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_collect_commits.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Confirm no `running` row can ever be committed**

The crash test above proves this empirically. Also confirm it by reading: open `collect_source` in full and check that every return path sets `run.status` to `"success"` or `"failed"` first. Paste that confirmation into your task report.

This matters twice over. A committed `running` row would break `consecutive_failures`, which counts backwards from the newest run and stops at the first non-`"failed"` status — a stray `running` would silently reset the circuit breaker on a source that has been failing for days. It also means **a second connection never observes `running`**, which is why Task 5 exposes an explicit `collecting` flag instead of inferring completion from run status. If you find a path that can return with `status == "running"`, stop and report it rather than working around it.

- [ ] **Step 6: Run the full suite and commit**

```bash
.venv/bin/pytest
git add src/reachstore/collect.py tests/test_collect_commits.py
git commit -m "feat: commit per source in collect_tier so progress is observable (I4)"
```

---

### Task 5: The collect endpoint

**Files:**
- Create: `src/reachstore/api/collect_runner.py`
- Modify: `src/reachstore/api/routes.py`, `src/reachstore/api/schemas.py`
- Test: `tests/test_api_collect.py`

**Interfaces:**
- Consumes: `collect_tier`, `build_registry(http, runner)`, `HttpxFetcher`, `SubprocessRunner`, `deps.get_session_factory`, `deps.raw_dir`
- Produces:
  - `collect_runner.run_collection(tier: int, force: bool) -> None`
  - `collect_runner.is_running() -> bool`
  - `POST /api/collect`
  - `SourcesResponse.collecting: bool` — the frontend's completion signal

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_collect.py`:

```python
import pytest
from fastapi.testclient import TestClient

from reachstore.api import collect_runner
from reachstore.api.app import create_app
from reachstore.api.deps import get_session


def make_client(session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


def test_collect_accepts_and_reports_started(session, monkeypatch):
    calls = []
    monkeypatch.setattr(
        collect_runner, "run_collection", lambda tier, force: calls.append((tier, force))
    )
    response = make_client(session).post("/api/collect", json={"tier": 1, "force": False})
    assert response.status_code == 202
    assert response.json()["started"] is True
    assert response.json()["tier"] == 1
    # TestClient runs background tasks before returning from the request.
    assert calls == [(1, False)]


def test_collect_rejects_a_second_run_while_one_is_in_flight(session, monkeypatch):
    monkeypatch.setattr(collect_runner, "is_running", lambda: True)
    response = make_client(session).post("/api/collect", json={"tier": 1, "force": False})
    assert response.status_code == 409
    assert response.json()["started"] is False
    assert response.json()["reason"]


def test_collect_rejects_an_invalid_tier(session):
    client = make_client(session)
    assert client.post("/api/collect", json={"tier": 0}).status_code == 422
    assert client.post("/api/collect", json={"tier": 9}).status_code == 422


def test_sources_endpoint_reports_whether_a_run_is_in_flight(session, monkeypatch):
    client = make_client(session)
    assert client.get("/api/sources").json()["collecting"] is False
    monkeypatch.setattr(collect_runner, "is_running", lambda: True)
    assert client.get("/api/sources").json()["collecting"] is True


def test_the_runner_opens_its_own_session_and_always_clears_the_flag(
    session, raw_dir, monkeypatch
):
    """The background task must not reuse the request-scoped session.

    FastAPI background tasks run after the response is sent, by which point
    the request session is already closed. This also pins the flag lifecycle:
    a run that raises must not leave `is_running()` stuck True, which would
    disable the Collect button until the server restarts.
    """

    class FakeSession:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    fake = FakeSession()
    monkeypatch.setattr(collect_runner, "get_session_factory", lambda: (lambda: fake))
    monkeypatch.setattr(collect_runner, "raw_dir", lambda: raw_dir)

    seen = {}

    def fake_collect_tier(sess, **kwargs):
        seen["session"] = sess
        seen["tier"] = kwargs["tier"]
        seen["force"] = kwargs["force"]
        seen["running_during"] = collect_runner.is_running()
        return []

    monkeypatch.setattr(collect_runner, "collect_tier", fake_collect_tier)
    collect_runner.run_collection(tier=2, force=True)

    assert seen["session"] is fake
    assert seen["session"] is not session
    assert seen["tier"] == 2 and seen["force"] is True
    assert seen["running_during"] is True
    assert fake.closed
    assert collect_runner.is_running() is False


def test_a_crashing_run_still_clears_the_flag(session, raw_dir, monkeypatch):
    class FakeSession:
        def close(self):
            pass

    monkeypatch.setattr(collect_runner, "get_session_factory", lambda: (lambda: FakeSession()))
    monkeypatch.setattr(collect_runner, "raw_dir", lambda: raw_dir)

    def boom(sess, **kwargs):
        raise RuntimeError("database gone")

    monkeypatch.setattr(collect_runner, "collect_tier", boom)
    collect_runner.run_collection(tier=1, force=False)  # must not raise
    assert collect_runner.is_running() is False
```

Every test that reaches `run_collection` monkeypatches `get_session_factory`. Without that the runner opens a real connection to `DATABASE_URL` — the development database, not the test one.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_api_collect.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reachstore.api.collect_runner'`.

- [ ] **Step 3: Create `src/reachstore/api/collect_runner.py`**

```python
from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime

from reachstore.adapters.base import HttpxFetcher, SubprocessRunner
from reachstore.adapters.registry import build_registry
from reachstore.api.deps import get_session_factory, raw_dir
from reachstore.collect import collect_tier

log = logging.getLogger(__name__)

_lock = threading.Lock()
_running = False


def is_running() -> bool:
    """Whether a collection run is in flight in this process.

    This is the frontend's completion signal. It cannot be inferred from
    fetch_run status instead: `collect_tier` only ever commits terminal
    statuses (see Task 4), so a reader never observes a "running" row.
    """
    return _running


def run_collection(tier: int, force: bool) -> None:
    """Run one tier to completion. Never raises.

    Opens its own session: FastAPI background tasks run after the response has
    been sent, so the request-scoped session is already closed by then.

    The guard flag is per-process. This slice is single-worker by design;
    running uvicorn with multiple workers would give each its own copy and
    defeat the guard, which would then need a Postgres advisory lock instead.
    """
    global _running
    with _lock:
        if _running:
            return
        _running = True

    session = get_session_factory()()
    try:
        collect_tier(
            session,
            tier=tier,
            registry=build_registry(HttpxFetcher(), SubprocessRunner()),
            raw_dir=raw_dir(),
            now=datetime.now(UTC),
            force=force,
        )
    except Exception:
        # A background task that raises produces an unhandled-exception
        # traceback from the ASGI layer after the response has already been
        # sent, which no client ever sees. Log it here instead.
        log.exception("collection run failed for tier %s", tier)
    finally:
        session.close()
        with _lock:
            _running = False
```

`datetime.now(UTC)` is permitted here: `collect_runner` is part of the API entrypoint, which the Global Constraints name alongside `cli.py`.

- [ ] **Step 4: Update `schemas.py`**

Add `collecting` to the existing `SourcesResponse`:

```python
class SourcesResponse(BaseModel):
    sources: list[SourceStatusOut]
    collecting: bool = False
```

And add the collect request/response models:

```python
from pydantic import BaseModel, Field


class CollectRequest(BaseModel):
    tier: int = Field(..., ge=1, le=3)
    force: bool = False


class CollectResponse(BaseModel):
    started: bool
    tier: int | None = None
    reason: str | None = None
```

Update the existing `from pydantic import BaseModel` line to include `Field`.

- [ ] **Step 5: Update `routes.py`**

Add to the `fastapi` import line: `BackgroundTasks`, `Response`. Add to the schema import: `CollectRequest`, `CollectResponse`. Add a new import:

```python
from reachstore.api import collect_runner
```

Change `list_sources` to report the flag:

```python
@router.get("/sources", response_model=SourcesResponse)
def list_sources(session: Session = Depends(get_session)) -> SourcesResponse:
    statuses = query.source_health(session)
    return SourcesResponse(
        sources=[SourceStatusOut(**vars(s)) for s in statuses],
        collecting=collect_runner.is_running(),
    )
```

Folding `collecting` into this response rather than adding a second endpoint means the client gets progress and completion from a single poll.

Add the collect handler:

```python
@router.post("/collect", response_model=CollectResponse, status_code=202)
def post_collect(
    body: CollectRequest, background: BackgroundTasks, response: Response
) -> CollectResponse:
    if collect_runner.is_running():
        response.status_code = 409
        return CollectResponse(
            started=False, reason="a collection run is already in progress"
        )
    background.add_task(collect_runner.run_collection, body.tier, body.force)
    return CollectResponse(started=True, tier=body.tier)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_api_collect.py tests/test_api_sources.py -v`
Expected: PASS (8 passed).

- [ ] **Step 7: Run the full suite and commit**

```bash
.venv/bin/pytest
git add src/reachstore/api tests/test_api_collect.py
git commit -m "feat: background collection endpoint with a concurrency guard"
```

---

### Task 6: Vite scaffold and the feed pane

**Files:**
- Create: `web/package.json`, `web/vite.config.js`, `web/index.html`, `web/src/main.jsx`, `web/src/App.jsx`, `web/src/api.js`, `web/src/styles.css`, `web/src/components/ItemList.jsx`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `GET /api/feed`
- Produces: `web/src/api.js` exporting `fetchFeed`, `fetchSearch`, `fetchItem`, `fetchSources`, `startCollect`; a Vite dev server rendering the feed

- [ ] **Step 1: Scaffold**

```bash
mkdir -p web && cd web
npm create vite@latest . -- --template react
npm install
```

Answer yes to any prompt about proceeding in a non-empty directory. Then remove the template's demo content:

```bash
rm -f src/App.css src/index.css && rm -rf src/assets public/vite.svg
```

- [ ] **Step 2: Confirm `.gitignore` covers build output**

```bash
cd .. && grep -q '^web/dist/$' .gitignore || echo 'web/dist/' >> .gitignore
grep -q 'node_modules' .gitignore || echo 'node_modules/' >> .gitignore
```

- [ ] **Step 3: Configure the dev proxy**

Replace `web/vite.config.js`:

```js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Proxying keeps the browser same-origin, which is why no CORS
    // middleware exists anywhere in this project.
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
```

- [ ] **Step 4: Create `web/src/api.js`**

```js
async function get(path, params) {
  const qs = params ? '?' + new URLSearchParams(params) : ''
  const res = await fetch(`/api${path}${qs}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
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

export const fetchSearch = (q, kind) => get('/search', { q, ...(kind ? { kind } : {}) })
export const fetchItem = (id) => get(`/items/${id}`)
export const fetchSources = () => get('/sources')

export async function startCollect(tier, force = false) {
  const res = await fetch('/api/collect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tier, force }),
  })
  return { ok: res.ok, ...(await res.json()) }
}
```

- [ ] **Step 5: Create `web/src/components/ItemList.jsx`**

```jsx
export default function ItemList({ items, selectedId, onSelect, onLoadMore, hasMore }) {
  if (items.length === 0) return <div className="item-list"><p className="empty">No items.</p></div>

  return (
    <div className="item-list">
      {items.map((item) => (
        <button
          key={item.id}
          className={`item-row${item.id === selectedId ? ' selected' : ''}`}
          onClick={() => onSelect(item.id)}
        >
          <div className="item-title">{item.title ?? '(untitled)'}</div>
          <div className="item-meta">
            {item.source_identifier} · {item.published_at?.slice(0, 10) ?? 'undated'}
          </div>
        </button>
      ))}
      {hasMore && <button className="load-more" onClick={onLoadMore}>Load more</button>}
    </div>
  )
}
```

- [ ] **Step 6: Create `web/src/App.jsx`**

```jsx
import { useEffect, useState } from 'react'
import { fetchFeed } from './api'
import ItemList from './components/ItemList'

export default function App() {
  const [items, setItems] = useState([])
  const [cursor, setCursor] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchFeed(null)
      .then((r) => { setItems(r.items); setCursor(r.next_cursor) })
      .catch((e) => setError(String(e)))
  }, [])

  const loadMore = () =>
    fetchFeed(cursor)
      .then((r) => { setItems((prev) => [...prev, ...r.items]); setCursor(r.next_cursor) })
      .catch((e) => setError(String(e)))

  return (
    <div className="app">
      <header className="header"><strong>reachstore</strong></header>
      {error && <p className="error">{error}</p>}
      <main className="panes">
        <ItemList
          items={items}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onLoadMore={loadMore}
          hasMore={cursor !== null}
        />
        <section className="detail">
          {selectedId ? <p>Item {selectedId} selected.</p> : <p className="empty">Select an item.</p>}
        </section>
      </main>
    </div>
  )
}
```

- [ ] **Step 7: Create `web/src/main.jsx` and `web/src/styles.css`**

`web/src/main.jsx`:

```jsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode><App /></React.StrictMode>
)
```

`web/src/styles.css`:

```css
:root { --bg:#111; --fg:#e8e8e8; --dim:#999; --line:#2c2c2c; --accent:#5b8cff; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
.app { display:flex; flex-direction:column; height:100vh; }
.header { padding:.7rem 1rem; border-bottom:1px solid var(--line); }
.panes { flex:1; display:flex; min-height:0; }
.item-list { flex:0 0 40%; overflow-y:auto; border-right:1px solid var(--line); }
.item-row { display:block; width:100%; text-align:left; background:none; color:inherit;
  border:0; border-bottom:1px solid var(--line); padding:.6rem .8rem; cursor:pointer; font:inherit; }
.item-row:hover { background:#1a1a1a; }
.item-row.selected { background:rgba(91,140,255,.14); }
.item-title { font-weight:600; font-size:.9rem; }
.item-meta { font-size:.75rem; color:var(--dim); margin-top:.15rem; }
.detail { flex:1; overflow-y:auto; padding:1rem 1.2rem; }
.empty { color:var(--dim); padding:.6rem .8rem; }
.error { color:#f87171; padding:.5rem 1rem; margin:0; }
.load-more { width:100%; padding:.6rem; background:none; color:var(--accent);
  border:0; border-bottom:1px solid var(--line); cursor:pointer; font:inherit; }
```

Confirm `web/index.html` (created by the Vite template) contains `<div id="root"></div>` and a script tag pointing at `/src/main.jsx`. Fix the script path if the template named the entry differently.

- [ ] **Step 8: Verify by hand**

Terminal one:

```bash
.venv/bin/python -c "from reachstore.api.app import serve; serve()"
```

Terminal two:

```bash
cd web && npm run dev
```

Open http://localhost:5173. Expected: real items listed newest-first with source labels, and a working "Load more" that appends without repeating a row.

- [ ] **Step 9: Commit**

`package-lock.json` must be committed — it is what pins the Node toolchain against drift, and the spec records toolchain rot as a risk mitigated by exactly this.

```bash
git add web .gitignore
git status --short web | grep -q package-lock.json && echo "lock file staged" || echo "WARNING: package-lock.json missing"
git commit -m "feat: Vite scaffold and the feed pane"
```

---

### Task 7: Search, item detail, and the health strip

**Files:**
- Create: `web/src/components/ItemDetail.jsx`, `web/src/components/SearchBar.jsx`, `web/src/components/HealthStrip.jsx`
- Modify: `web/src/App.jsx`, `web/src/styles.css`

**Interfaces:**
- Consumes: `GET /api/items/{id}`, `GET /api/search`, `GET /api/sources`, `POST /api/collect`
- Produces: the complete two-pane UI, minus live polling (Task 8)

- [ ] **Step 1: Create `web/src/components/ItemDetail.jsx`**

```jsx
export default function ItemDetail({ item }) {
  if (!item) return <p className="empty">Select an item.</p>
  return (
    <article>
      <h2 className="detail-title">
        <a href={item.url} target="_blank" rel="noreferrer">{item.title ?? '(untitled)'}</a>
      </h2>
      <p className="detail-meta">
        {item.source_identifier} · {item.published_at?.slice(0, 10) ?? 'undated'}
        {item.author_handle ? ` · ${item.author_handle}` : ''}
      </p>
      <div className="detail-body">{item.content_text}</div>
    </article>
  )
}
```

- [ ] **Step 2: Create `web/src/components/SearchBar.jsx`**

```jsx
import { useState } from 'react'

export default function SearchBar({ onSearch, onClear, onCollect, collecting }) {
  const [q, setQ] = useState('')
  const [tier, setTier] = useState(1)

  const submit = (e) => {
    e.preventDefault()
    if (q.trim()) onSearch(q.trim())
    else onClear()
  }

  return (
    <form className="searchbar" onSubmit={submit}>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="search collected items…"
        aria-label="search"
      />
      {q && <button type="button" onClick={() => { setQ(''); onClear() }}>clear</button>}
      <select value={tier} onChange={(e) => setTier(Number(e.target.value))} aria-label="tier">
        <option value={1}>Tier 1</option>
        <option value={2}>Tier 2</option>
        <option value={3}>Tier 3</option>
      </select>
      <button type="button" onClick={() => onCollect(tier)} disabled={collecting}>
        {collecting ? 'Collecting…' : 'Collect'}
      </button>
    </form>
  )
}
```

- [ ] **Step 3: Create `web/src/components/HealthStrip.jsx`**

```jsx
import { useState } from 'react'

export default function HealthStrip({ sources }) {
  const [open, setOpen] = useState(false)
  const healthy = sources.filter((s) => s.last_status === 'success').length
  const failing = sources.filter((s) => s.last_status === 'failed').length

  return (
    <div className="health">
      <button className="health-summary" onClick={() => setOpen(!open)}>
        {open ? '▾' : '▸'} {sources.length} sources · {healthy} healthy · {failing} failing
      </button>
      {open && (
        <ul className="health-list">
          {sources.map((s) => (
            <li key={s.source_id}>
              <span className={`dot ${s.last_status ?? 'never'}`} />
              <span className="health-id">{s.identifier}</span>
              <span className="health-meta">
                {s.item_count} items
                {s.consecutive_failures > 0 && ` · ${s.consecutive_failures} failures`}
              </span>
              {s.error_text && <div className="health-error">{s.error_text}</div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Rewrite `web/src/App.jsx`**

```jsx
import { useCallback, useEffect, useState } from 'react'
import { fetchFeed, fetchItem, fetchSearch, fetchSources, startCollect } from './api'
import HealthStrip from './components/HealthStrip'
import ItemDetail from './components/ItemDetail'
import ItemList from './components/ItemList'
import SearchBar from './components/SearchBar'

export default function App() {
  const [items, setItems] = useState([])
  const [cursor, setCursor] = useState(null)
  const [selected, setSelected] = useState(null)
  const [sources, setSources] = useState([])
  const [searching, setSearching] = useState(false)
  const [collecting, setCollecting] = useState(false)
  const [error, setError] = useState(null)

  const fail = (e) => setError(String(e))

  const loadFeed = useCallback(() => {
    setSearching(false)
    fetchFeed(null).then((r) => { setItems(r.items); setCursor(r.next_cursor) }).catch(fail)
  }, [])

  const refreshSources = useCallback(
    () => fetchSources()
      .then((r) => { setSources(r.sources); setCollecting(r.collecting) })
      .catch(fail),
    []
  )

  // Reading `collecting` from the server rather than only from local state
  // means a page reload during a run picks the progress view back up.
  useEffect(() => { loadFeed(); refreshSources() }, [loadFeed, refreshSources])

  const select = (id) => fetchItem(id).then(setSelected).catch(fail)

  const search = (q) => {
    setSearching(true)
    fetchSearch(q).then((r) => { setItems(r.items); setCursor(null) }).catch(fail)
  }

  const loadMore = () =>
    fetchFeed(cursor)
      .then((r) => { setItems((prev) => [...prev, ...r.items]); setCursor(r.next_cursor) })
      .catch(fail)

  const collect = async (tier) => {
    setError(null)
    try {
      const res = await startCollect(tier)
      if (!res.ok) { setError(res.reason ?? 'could not start collection'); return }
      setCollecting(true)
    } catch (e) { fail(e) }
  }

  return (
    <div className="app">
      <header className="header">
        <SearchBar onSearch={search} onClear={loadFeed} onCollect={collect} collecting={collecting} />
        <HealthStrip sources={sources} />
      </header>
      {error && <p className="error">{error}</p>}
      <main className="panes">
        <ItemList
          items={items}
          selectedId={selected?.id}
          onSelect={select}
          onLoadMore={loadMore}
          hasMore={!searching && cursor !== null}
        />
        <section className="detail"><ItemDetail item={selected} /></section>
      </main>
    </div>
  )
}
```

`hasMore` is false while searching: `/api/search` returns one ranked page and has no cursor, so a "Load more" there would have nothing to ask for.

- [ ] **Step 5: Append to `web/src/styles.css`**

```css
.searchbar { display:flex; gap:.4rem; align-items:center; }
.searchbar input { flex:1; padding:.4rem .6rem; background:#1a1a1a; color:var(--fg);
  border:1px solid var(--line); border-radius:4px; font:inherit; }
.searchbar button, .searchbar select { padding:.4rem .7rem; background:#1a1a1a; color:var(--fg);
  border:1px solid var(--line); border-radius:4px; cursor:pointer; font:inherit; }
.searchbar button:disabled { opacity:.55; cursor:default; }
.health { margin-top:.5rem; }
.health-summary { background:none; border:0; color:var(--dim); cursor:pointer; font:inherit; padding:0; }
.health-list { list-style:none; margin:.4rem 0 0; padding:0; font-size:.8rem; }
.health-list li { padding:.25rem 0; }
.dot { display:inline-block; width:.5rem; height:.5rem; border-radius:50%; margin-right:.45rem; }
.dot.success { background:#4ade80; } .dot.failed { background:#f87171; } .dot.never { background:#666; }
.health-id { margin-right:.5rem; }
.health-meta { color:var(--dim); }
.health-error { color:#f87171; font-size:.72rem; margin-left:.95rem; }
.detail-title { margin:0 0 .2rem; font-size:1.05rem; }
.detail-title a { color:var(--fg); }
.detail-meta { color:var(--dim); font-size:.78rem; margin:0 0 .9rem; }
.detail-body { white-space:pre-wrap; }
```

- [ ] **Step 6: Verify by hand**

With both servers running, confirm each of these: searching narrows the list; `clear` restores the full feed; clicking a row fills the right pane with full stored text and a working external link; the health strip expands and shows the failing source's `error_text`.

- [ ] **Step 7: Commit**

```bash
git add web
git commit -m "feat: search, item detail, and the health strip"
```

---

### Task 8: Live progress during collection

**Files:**
- Modify: `web/src/App.jsx`

**Interfaces:**
- Consumes: `GET /api/sources` — specifically its `collecting` field (Task 5)
- Produces: polling that starts on collect and stops when the server reports the run finished

- [ ] **Step 1: Add the polling effect to `App.jsx`**

Insert after the existing mount `useEffect`:

```jsx
  useEffect(() => {
    if (!collecting) return
    let cancelled = false
    const id = setInterval(async () => {
      try {
        const r = await fetchSources()
        if (cancelled) return
        // Per-source rows update as each source commits (Task 4), so the
        // health strip fills in progressively. `collecting` is the server's
        // own flag -- run status cannot be used, because collect_tier only
        // ever commits terminal statuses and a reader never sees "running".
        setSources(r.sources)
        if (!r.collecting) {
          setCollecting(false)
          loadFeed()
        }
      } catch (e) {
        if (!cancelled) { setError(String(e)); setCollecting(false) }
      }
    }, 2000)
    return () => { cancelled = true; clearInterval(id) }
  }, [collecting, loadFeed])
```

The cleanup both clears the interval and sets `cancelled`, so a request still in flight at unmount cannot call `setState` on a dead component.

- [ ] **Step 2: Verify by hand**

With both servers running, select **Tier 1** and click **Collect**. Expected: the button reads "Collecting…" and is disabled; the health strip's counts and `last_run_at` update as sources finish; the button re-enables and the feed reloads on its own. Then click Collect twice quickly — the second click must surface "a collection run is already in progress" rather than starting a second run.

- [ ] **Step 3: Commit**

```bash
git add web/src/App.jsx
git commit -m "feat: poll source health while a collection run is in flight"
```

---

### Task 9: Playwright smoke test

**Files:**
- Create: `web/tests/seed_e2e.py`, `web/tests/smoke.spec.js`, `web/playwright.config.js`
- Modify: `web/package.json`

**Interfaces:**
- Consumes: the running app
- Produces: `npm run test:e2e` — seeds the test database, starts both servers, runs the smoke test

The spec requires this test to drive the **test** database, not the development one. That matters for a reason worth stating: asserting against whatever happens to be in `DATABASE_URL` makes the test pass or fail based on data no one controls. It is seeded instead, so `npm run test:e2e` behaves identically on a fresh clone.

- [ ] **Step 1: Install the test runner**

```bash
cd web && npm install -D @playwright/test
```

Browsers are already installed on this machine. Do not run `npx playwright install`.

- [ ] **Step 2: Write the seed script**

Create `web/tests/seed_e2e.py`:

```python
"""Seed the TEST database with deterministic data for the Playwright smoke test.

Run from the repo root:  .venv/bin/python web/tests/seed_e2e.py

Idempotent -- `upsert_items` conflicts on (source_id, external_id) and skips,
so re-running adds nothing. Safe to run before every e2e invocation.

Note: pytest's `engine` fixture runs DROP SCHEMA on this same database at
session scope, so do not run the Python suite and the e2e suite concurrently.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from reachstore.adapters.base import NormalizedItem
from reachstore.config import get_settings
from reachstore.db import make_engine, make_session_factory
from reachstore.models import Source
from reachstore.store import upsert_items

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
COUNT = 12
RAW_DIR = Path("data/raw-e2e")


def main() -> None:
    settings = get_settings()
    url = settings.test_database_url
    # Same guard as conftest.py: never touch a database that is not clearly
    # the test one. This script migrates and writes; pointing it at the
    # development database would be destructive.
    if not url or not url.endswith("_test"):
        raise SystemExit("TEST_DATABASE_URL must be set and end in '_test'. Refusing to seed.")

    os.environ["ALEMBIC_DATABASE_URL"] = url
    command.upgrade(Config("alembic.ini"), "head")

    session = make_session_factory(make_engine(url))()
    try:
        source = session.execute(
            select(Source).where(
                Source.kind == "rss", Source.identifier == "https://e2e/feed"
            )
        ).scalars().one_or_none()
        if source is None:
            source = Source(
                kind="rss",
                identifier="https://e2e/feed",
                tier=1,
                config_json={},
                created_at=NOW,
            )
            session.add(source)
            session.flush()

        items = [
            NormalizedItem(
                external_id=f"e2e-{i}",
                url=f"https://e2e/{i}",
                title=f"Smoke test article {i}",
                content_text=(
                    f"Article {i} about collecting and searching. "
                    + "This paragraph exists so the detail pane has real length. " * 6
                ),
                published_at=NOW - timedelta(days=i),
            )
            for i in range(COUNT)
        ]
        new = upsert_items(
            session,
            source_id=source.id,
            items=items,
            owner_user_id=None,
            raw_dir=RAW_DIR,
            now=NOW,
        )
        session.commit()
        print(f"seeded {COUNT} items ({new} new) into {url.rsplit('/', 1)[-1]}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the seed script on its own**

```bash
cd .. && .venv/bin/python web/tests/seed_e2e.py && .venv/bin/python web/tests/seed_e2e.py
```

Expected: the first run reports `12 items (12 new)`, the second `12 items (0 new)`. If the second run reports new items, idempotency is broken — stop and investigate rather than continuing.

- [ ] **Step 4: Create `web/playwright.config.js`**

```js
import fs from 'node:fs'
import { defineConfig } from '@playwright/test'

// The API reads its URL from settings, which prefer a real environment
// variable over .env. Point DATABASE_URL at the test database so the smoke
// test asserts against seeded data rather than whatever the dev database
// happens to hold.
const dotenv = Object.fromEntries(
  fs
    .readFileSync('../.env', 'utf8')
    .split('
')
    .filter((line) => line.includes('=') && !line.trim().startsWith('#'))
    .map((line) => {
      const i = line.indexOf('=')
      return [line.slice(0, i).trim(), line.slice(i + 1).trim()]
    })
)
const TEST_DB = dotenv.TEST_DATABASE_URL
if (!TEST_DB) throw new Error('TEST_DATABASE_URL is missing from .env')

export default defineConfig({
  testDir: './tests',
  use: { baseURL: 'http://localhost:5173' },
  // Both servers, so `npm run test:e2e` is one command. reuseExistingServer
  // is false for the API: an already-running dev server would be pointed at
  // the development database and would silently invalidate the test.
  webServer: [
    {
      command: 'cd .. && .venv/bin/python -c "from reachstore.api.app import serve; serve()"',
      url: 'http://127.0.0.1:8000/api/sources',
      env: { DATABASE_URL: TEST_DB },
      reuseExistingServer: false,
      timeout: 30000,
    },
    {
      command: 'npm run dev',
      url: 'http://localhost:5173',
      reuseExistingServer: true,
      timeout: 30000,
    },
  ],
})
```

`reuseExistingServer: false` on the API means port 8000 must be free. Stop any hand-started API server before running the suite.

- [ ] **Step 5: Write the smoke test**

Create `web/tests/smoke.spec.js`:

```js
import { expect, test } from '@playwright/test'

test('the feed lists items and clicking one opens its full text', async ({ page }) => {
  await page.goto('/')

  const rows = page.locator('.item-row')
  await expect(rows).toHaveCount(12)

  await expect(page.locator('.health-summary')).toContainText('1 sources')

  // Seeded newest-first: day 0 is the most recent.
  await expect(rows.first().locator('.item-title')).toHaveText('Smoke test article 0')
  await rows.first().click()

  const detail = page.locator('.detail-body')
  await expect(detail).toBeVisible()
  await expect(page.locator('.detail-title')).toContainText('Smoke test article 0')
  expect((await detail.innerText()).length).toBeGreaterThan(240)
})

test('searching narrows the list and clearing restores it', async ({ page }) => {
  await page.goto('/')
  const rows = page.locator('.item-row')
  await expect(rows).toHaveCount(12)

  await page.getByLabel('search').fill('zzzznotarealterm')
  await page.getByLabel('search').press('Enter')
  // Scoped to the list: the detail pane also renders .empty when nothing is
  // selected, and an unscoped locator would match two elements and fail
  // Playwright's strict mode.
  await expect(page.locator('.item-list .empty')).toBeVisible()

  await page.getByLabel('search').fill('collecting')
  await page.getByLabel('search').press('Enter')
  await expect(rows).toHaveCount(12)

  await page.getByRole('button', { name: 'clear' }).click()
  await expect(rows).toHaveCount(12)
})

test('the health strip expands to show per-source detail', async ({ page }) => {
  await page.goto('/')
  await page.locator('.health-summary').click()
  await expect(page.locator('.health-id')).toHaveText('https://e2e/feed')
  await expect(page.locator('.health-meta')).toContainText('12 items')
})
```

Every assertion is a fixed number because the data is seeded. If one fails, the app is wrong — do not relax the assertion to match observed output.

- [ ] **Step 6: Add the scripts**

In `web/package.json`, add to `scripts`:

```json
    "seed:e2e": "cd .. && .venv/bin/python web/tests/seed_e2e.py",
    "test:e2e": "npm run seed:e2e && playwright test"
```

- [ ] **Step 7: Run the tests**

```bash
cd web && npm run test:e2e
```

Expected: 3 passed. The seed runs first, so this works from a clean checkout with no manual collection.

- [ ] **Step 8: Run the Python suite and commit**

`package-lock.json` must be committed — it is what pins the Node toolchain against drift.

```bash
cd .. && .venv/bin/pytest
git add web
git status --short web | grep package-lock.json || echo "WARNING: package-lock.json not staged"
git commit -m "test: hermetic Playwright smoke test against the seeded test database"
```

---

### Task 10: Update the living architecture doc

**Files:**
- Modify: `docs/architecture.md`

`docs/architecture.md` declares itself a living document. It currently describes the web layer as planned and states "86 tests". Both are stale once Task 9 lands.

- [ ] **Step 1: Update the stale claims**

Make these edits, verifying each number rather than copying it from this plan:

1. Header date and the `**Status:**` line — the web UI and API are built, not planned.
2. §2 layer diagram — drop "(planned)" from `api/`.
3. §3 third invariant — "Only `cli.py` — and, once built, `api/routes.py`" becomes a statement about `cli.py` and the `api/` package, `collect_runner.py` included.
4. §3 fourth invariant and §8 — replace "86 tests" with the real count from `.venv/bin/pytest`.
5. §6 — note that `collect_tier` commits per source, and why (progress visibility plus crash-durability of the failure record).
6. §7 — retitle to "Web layer", describe what exists: the endpoints, `DEFAULT_USER_ID`, the module-level engine, the loopback guard, and `collecting` as the completion signal with the reason run status cannot serve that role.
7. §8 — add the two commands needed to run the app.
8. §9 — add a decision entry for the `collecting` flag over inferring completion from `fetch_runs`.

- [ ] **Step 2: Verify the numbers**

```bash
.venv/bin/pytest -q | tail -3
grep -rn "datetime.now\|utcnow" src/
grep -rn "select(" src/reachstore/api/ || echo "no SQL in the API layer -- correct"
```

Every count written into the doc must come from this output.

- [ ] **Step 3: Commit**

```bash
git add docs/architecture.md
git commit -m "docs: update architecture.md now that the web layer is built"
```

---

## Definition of Done

- `.venv/bin/pytest` passes; ~111 tests (86 from Plan 1, plus 25 added here: 4 / 5 / 7 / 3 / 6 across Tasks 1–5)
- `cd web && npm run test:e2e` passes (3 tests) from a clean checkout, with no manual collection — it seeds the test database itself
- With both servers running, http://localhost:5173 lists real items, searches them, opens full stored text, shows source health with error text, and runs a collection whose progress is visible and which cannot be started twice
- `.venv/bin/python -c "from reachstore.api.app import serve; serve('0.0.0.0')"` refuses to start
- `grep -rn "datetime.now\|utcnow" src/` returns hits only in `cli.py` and `src/reachstore/api/`
- `grep -rn "select(" src/reachstore/api/` returns nothing
- `docs/architecture.md` describes the web layer in the present tense with a verified test count

## Out of scope

Authentication, `ask()` synthesis, adding or removing sources from the browser, subscriptions, deployment beyond localhost, and multi-worker serving. Each is recorded in the spec's out-of-scope section; the multi-worker case is called out in `collect_runner.run_collection`'s docstring because the guard's correctness depends on it.
