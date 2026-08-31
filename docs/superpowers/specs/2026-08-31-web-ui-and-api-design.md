# Web UI and JSON API — Design

**Date:** 2026-08-31
**Status:** Approved
**Supersedes ordering in:** `2026-08-13-agent-reach-knowledge-store-design.md` (Plan 4 pulled ahead of the rest of Plan 2)

## 1. Overview

A browser interface for `reachstore`, backed by a thin FastAPI layer over the existing store. It reads the 212 collected items, searches them, shows per-source health, and triggers collection runs that report progress live.

This is the first slice of the web UI, pulled forward ahead of authentication and LLM synthesis. The store has been usable only from a terminal since Plan 1 shipped; making it visible is worth more right now than making it multi-user.

## 2. Goals and non-goals

**Goals**

- Browse collected items newest-first, with working pagination
- Full-text search with the ranking already built into `query.search`
- Read an item's full stored text without leaving the page
- See per-source health: last status, failure streak, item counts
- Trigger a collection run and watch sources update as it proceeds

**Non-goals for this slice**

- Authentication, registration, sessions, or multi-user access
- Adding, editing, or deleting sources from the browser (CLI only)
- Subscriptions management
- LLM synthesis / `ask()`
- Deployment beyond `localhost`
- Tier-2/3 collectors

## 3. Key decisions

| Decision | Choice | Why |
|---|---|---|
| Auth | None; loopback only | 3× smaller build; tenant seam stays live for Plan 2 |
| Scope | Read + trigger collection | Read-only would mean returning to the terminal for fresh data |
| Collect UX | Background run, client polls | A blocking request feels frozen and can time out |
| Layout | Two-pane reader | Full text is already stored; a reading pane uses what we have |
| Serving | Vite dev proxy; FastAPI serves `dist/` in production | Hot reload while building; one process when deployed |
| Frontend | React + Vite | Per the approved 2026-08-13 design |
| User identity | `DEFAULT_USER_ID = 1`, one definition | Keeps tenant plumbing exercised rather than stubbed |

## 4. Architecture

Two new units, plus four small additive changes to existing modules (see §10).

```
src/reachstore/api/
  deps.py       module-level engine, request-scoped session dependency
  schemas.py    Pydantic response models
  routes.py     endpoint handlers — no SQL, no business logic
  app.py        FastAPI app; mounts routes, serves web/dist when present

web/
  package.json
  vite.config.js        dev proxy /api -> http://127.0.0.1:8000
  index.html
  src/main.jsx
  src/App.jsx           two-pane shell + polling loop
  src/api.js            fetch wrappers, one per endpoint
  src/components/SearchBar.jsx
  src/components/HealthStrip.jsx
  src/components/ItemList.jsx
  src/components/ItemDetail.jsx
```

`store.py` and all adapters are untouched. `models.py` and `query.py` take the additive changes in §10. The API calls `query` and `collect` functions and serialises their results; it constructs no SQL, preserving the Global Constraint that all SQL lives in `store.py` and `query.py`.

### 4.1 The composition root

`cli.py`'s `_session()` calls `make_engine(...)` on every invocation. That is correct for a one-shot process and wrong for a server — each request would create a new connection pool and never release it, exhausting Postgres connections under any sustained use.

`api/deps.py` therefore owns:

- one `Engine`, created once at module import
- one `sessionmaker` bound to it
- `get_session()` — a FastAPI dependency yielding a session per request and closing it in a `finally`

`cli.py` keeps its existing `_session()` unchanged. A one-shot CLI does not need pooling, and altering it would require re-reviewing completed work for no benefit.

### 4.2 User identity

`DEFAULT_USER_ID = 1` is defined once, in `deps.py`, and passed by every route to the `query` functions that take `user_id`. Plan 2 replaces the constant with a value read from the session; no route signature changes.

This keeps the tenant-isolation path live and exercised. Stubbing it out — passing `None`, or dropping the parameter — would leave Plan 2 to thread a new argument through every call site and re-test each one.

## 5. API surface

All paths are prefixed `/api`. All responses are JSON.

### `GET /api/feed`

Query parameters: `limit` (default 50), `before_published_at` (ISO-8601, optional), `before_id` (int, optional).

Calls `query.feed(session, user_id=DEFAULT_USER_ID, limit=..., before_published_at=..., before_id=...)`.

Returns:

```json
{
  "items": [ItemSummary, ...],
  "next_cursor": {"published_at": "2026-08-06T19:49:34+00:00", "id": 42}
}
```

`next_cursor` is `null` when fewer than `limit` items were returned. **The cursor is compound.** Fix F2 of the Plan 1 fix wave demonstrated that an id-only cursor over a `(published_at DESC NULLS LAST, id DESC)` ordering both duplicates and drops rows. Clients must pass both values back.

### `GET /api/search`

Query parameters: `q` (required), `kind` (optional), `limit` (default 50).

Calls `query.search(session, user_id=DEFAULT_USER_ID, q=..., kinds=[kind] if kind else None, limit=...)`.

Returns `{"items": [ItemSummary, ...]}`. No pagination in this slice — `search` is relevance-ordered and capped at `MAX_LIMIT`.

### `GET /api/items/{item_id}`

Calls `query.get_item(session, user_id=DEFAULT_USER_ID, item_id=...)`. Returns `ItemDetail`, or `404` when the item does not exist **or is not visible to this user** — the two cases are deliberately indistinguishable, so the endpoint cannot be used to probe for the existence of another user's private items once Plan 2 adds real users.

### `GET /api/sources`

Calls `query.source_health(session)`. Returns `{"sources": [SourceStatusOut, ...]}`.

Note `source_health` takes no `user_id` — it is a global operator view, as established by fix F4. This endpoint inherits that and must be reconsidered when Plan 2 adds real users.

### `POST /api/collect`

Body: `{"tier": 1, "force": false}`.

Returns `202 Accepted` with `{"started": true, "tier": 1}` immediately, having scheduled the run as a background task. Returns `409 Conflict` with `{"started": false, "reason": "a collection run is already in progress"}` when one is in flight.

### 5.1 Response models

```python
class ItemSummary(BaseModel):
    id: int
    title: str | None
    url: str
    author_handle: str | None
    published_at: datetime | None
    source_id: int
    source_kind: str          # requires the relationship added in §10
    source_identifier: str    # requires the relationship added in §10
    excerpt: str              # first 240 chars of content_text, whitespace-collapsed

class ItemDetail(ItemSummary):
    content_text: str         # full stored text
    fetched_at: datetime

class SourceStatusOut(BaseModel):
    source_id: int
    kind: str
    identifier: str
    last_status: str | None
    last_run_at: datetime | None
    consecutive_failures: int
    needs_attention: bool
    error_text: str | None    # added to query.SourceStatus in §10
    item_count: int           # added to query.SourceStatus in §10
```

`ItemSummary` carries `source_kind` and `source_identifier` so the list can label each row without a request per item. **`Item` currently has no relationship to `Source`**, so this requires the ORM change in §10 — the API cannot join for itself without building SQL, which the Global Constraint forbids.

`SourceStatusOut` mirrors `query.SourceStatus` (`source_id`, `kind`, `identifier`, `last_status`, `last_run_at`, `consecutive_failures`, `needs_attention`) plus two fields §10 adds. `tier` is deliberately absent — the tier selector offers 1/2/3 from a constant rather than deriving them from data.

## 6. Background collection

`POST /api/collect` schedules `collect_tier` via FastAPI's `BackgroundTasks`.

**The task builds its own session.** Background tasks run after the response is sent, at which point the request-scoped session from `get_session()` is closed. Reusing it raises at runtime — and only under real HTTP, so a test calling the handler directly would not catch it. The task opens a session from the shared `sessionmaker`, runs `collect_tier`, and closes it in a `finally`.

**A module-level flag prevents concurrent runs.** Set before scheduling, cleared in the task's `finally`. A second `POST` while it is set returns `409`.

This flag is per-process. Running `uvicorn --workers N` with N > 1 would give each worker its own copy and defeat it. **This slice is single-worker by design**; if Plan 4 introduces multiple workers, the guard must move to an advisory lock in Postgres.

**Progress reporting reuses existing state.** The client polls `GET /api/sources` every 2 seconds while a run is active. `fetch_runs` already records `started_at`, `finished_at`, `status`, `items_found`, and `items_new` per source, and `source_health` already reads it. No new table, no new status endpoint.

## 7. Frontend

Layout **A**, two-pane reader:

- **Header strip** — search input, tier selector, Collect button, and a compact health summary (`3 sources · 2 healthy · 1 failing`) that expands to the full per-source list on click
- **Left pane (~40%)** — scrolling item list; each row shows title, source identifier, and date. Infinite scroll using the compound cursor
- **Right pane** — the selected item's full stored text, its title as a link to the original URL, and its metadata

State lives in `App.jsx`: the item list, the selected item, the search query, and whether a collection run is active. No state library — this is four components and one fetch layer.

While a run is active, `App.jsx` polls `/api/sources` on a 2s interval and stops when every source's `last_status` is terminal.

## 8. Security

There is no authentication. The only control is the network boundary, so it is enforced rather than documented:

**`app.py` refuses to start unless the bind host is a loopback address**, unless `REACHSTORE_ALLOW_NONLOCAL=1` is set explicitly. Binding `0.0.0.0` on an untrusted network would expose the entire store, including any private items added later, to anyone who can reach the port.

**No CORS middleware.** Vite proxies `/api` in development and FastAPI serves the built assets in production — same-origin in both cases. CORS appearing in this codebase means something is misconfigured.

**`404` rather than `403`** for items outside the caller's visibility, per §5.

## 9. Testing

**API** — pytest with FastAPI's `TestClient`, overriding the `get_session` dependency to yield the existing `conftest.py` session fixture. Every endpoint then runs against real Postgres inside the per-test rollback transaction. Coverage: each endpoint's happy path; `404` for a missing item; `409` for a concurrent collect; `422` for malformed parameters; and a compound-cursor pagination walk asserting every item appears exactly once across pages.

**Background task** — a test that the task builds its own session rather than the request's, since this is the failure mode that only appears under real HTTP.

**Frontend** — one Playwright smoke test: load the page, assert items render, click one, assert the detail pane fills, assert the health strip shows the source count. Not component unit tests; for four components they would cost more than they catch.

**The whole suite must remain offline.** The Playwright test drives a locally-served build against the test database.

## 10. Changes to existing code

Four. Each is required by this build, not opportunistic — and three were found by reviewing this spec against the actual code rather than against memory of it.

**1. `Item` gains a relationship to `Source`.** `models.py` currently has no relationship and no denormalised `kind`/`identifier` on `items`, so there is no way to label a feed row with its source. The API cannot join for itself — that would be SQL outside `query.py`. Add `source: Mapped[Source] = relationship()` on `Item`, and apply `selectinload(Item.source)` inside `query.feed`, `query.search`, and `query.get_item` so a 50-item page costs two queries rather than 51. The return type stays `list[Item]`; only the loading strategy changes.

**2. `query.SourceStatus` gains `error_text` and `item_count`.** The current dataclass carries neither, so the health strip could show that a source failed but not why, and could not show how much it has contributed. `error_text` comes from the same latest-`fetch_run` lookup `source_health` already performs; `item_count` needs one grouped count. Both stay inside `query.py`.

**3. `collect_tier` commits per source.** Finding I4 of the Plan 1 final review recommended this and deferred it as non-blocking for a CLI. It is blocking for a live progress view: `collect_tier` currently commits once at the end, so a 30-second run would show no change and then everything at once. The review specified the required care — a crash between a run row's creation and its terminal status would leave a committed `running` row, and `consecutive_failures` breaks its streak on any non-`failed` status, so a stale `running` must either not be committed or be treated as `failed` in the streak scan.

**4. A Global Constraint is reworded.** "Only the CLI reads the real clock" becomes **"Only entrypoints read the real clock — `cli.py` and `api/routes.py`. Never `query`, `collect`, `store`, or any adapter."** The API is a second entrypoint and must supply `now` to `collect_tier`. The intent is unchanged; only the enumeration was stale.

Changes 1 and 2 touch `models.py` and `query.py`, both completed and reviewed in Plan 1. Each is additive: no existing signature changes, no existing test should need modification. Any test that does need modifying is a signal to stop and reconsider.

## 11. Build order

1. `Item.source` relationship + `selectinload` in the three read functions (§10.1), and `error_text` / `item_count` on `SourceStatus` (§10.2) — the store-layer prerequisites, tested against the existing suite
2. `deps.py` + `app.py` + `GET /api/sources` — proves wiring end to end with the smallest surface
3. Read endpoints: `/api/feed`, `/api/search`, `/api/items/{id}`
4. `collect_tier` per-source commit (§10.3), with its tests
5. `POST /api/collect` + the concurrency guard
6. Vite scaffold + `api.js` + the two-pane shell rendering the feed
7. Search, item detail, health strip
8. Polling during collection
9. Playwright smoke test

Each step is independently testable, and steps 1–5 are usable from `curl` before any frontend exists.

## 12. Risks

| Risk | Mitigation |
|---|---|
| Background task uses the closed request session | Task opens its own; explicit test |
| Server bound to a public interface | Refuses to start off-loopback without an explicit override |
| Concurrent collect runs | Module-level flag; documented as single-worker only |
| Compound cursor implemented wrongly again | Pagination walk test asserting no duplicates and no gaps |
| Node toolchain rots | `package-lock.json` committed; `node_modules` already gitignored |
| Per-source commit leaves stale `running` rows | Handled per the I4 guidance; covered by a crash-simulation test |

## 13. Out of scope, recorded for later

- Auth, registration, sessions — Plan 2
- `ask()` LLM synthesis — Plan 2
- Add/remove sources from the browser — a later slice
- Subscriptions write path — Plan 2; `search(subscribed_only=True)` remains unexercisable until then
- Multi-worker deployment — Plan 4; requires replacing the in-process collect guard
