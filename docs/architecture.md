# reachstore — Architecture

**Living document.** Updated as the system changes. Last updated 2026-09-19.

A persistent knowledge store: it collects content from other sites, stores it raw, and searches it at query time. Built on [Agent-Reach](https://github.com/Panniantong/Agent-Reach), which supplies installation and credentials for the upstream tools; reachstore supplies the persistence Agent-Reach lacks.

**Status:** Plan 1 (core store + Tier-1 collection) and the web UI and JSON API are shipped and running. Plans for collectors and deployment remain unwritten.

---

## 1. The one idea

**Store raw, judge relevance at query time.** Filtering at ingest is an irreversible decision made with the least information available — you cannot recover an item you declined to store. So collection is deliberately indiscriminate and every judgement happens on read.

Two consequences run through the whole design: ingestion must be *idempotent* (safe to re-run forever without duplicating), and the raw upstream payload is kept on disk so a future parser change can reprocess history without re-scraping.

---

## 2. Layers

Each layer depends only on those below it.

```
        cli.py            api/                     ← entrypoints; the only clock readers
          │                 │
          └────────┬────────┘
                   ▼
          collect.py                               ← orchestration; no SQL
                   │
        ┌──────────┼──────────┐
        ▼          ▼          ▼
    store.py   query.py   adapters/                ← writes │ reads │ the outside world
        │          │          │
        └──────────┴──────────┘
                   ▼
              models.py                            ← 9 tables, Postgres 16
```

| Module | Responsibility | Rule |
|---|---|---|
| `models.py` | SQLAlchemy models, 9 tables | `TIMESTAMPTZ` throughout; `content_tsv` is a generated column |
| `store.py` | **The only writer of items** | Idempotent via `ON CONFLICT DO NOTHING` |
| `query.py` | **The only reader** | Owns `visible_to`, the sole tenant predicate |
| `adapters/` | One platform each | Never import `sqlalchemy`; all I/O injected |
| `collect.py` | Orchestration, isolation, backoff | Builds no SQL; calls `store` and `query` |
| `cli.py` | Composition root | Constructs real dependencies; reads the clock |

---

## 3. Invariants

These are enforced, not aspirational. Every one was verified tree-wide by the Plan 1 final review.

**All content SQL lives in `store.py` and `query.py`.** No other module in `src/` builds a query against a content table (test fixtures under `tests/` and `web/tests/` set up state directly, as fixtures do). When `collect.py` needed three queries, they were added to `query.py` rather than inlined — the constraint won over the reference implementation. Authentication widened this to *one owning module per table* (below) rather than weakening it: `api/auth.py` may query `users`, `sessions`, and `invites`, and nothing else may.

**The tenant predicate appears in exactly one function.** `query.visible_to(user_id)` returns `owner_user_id IS NULL OR owner_user_id = :user_id`. `get_item`, `feed`, and `search` all call it; none re-expresses it. This is the security boundary of a multi-tenant store, and a second copy is how it erodes.

**No wall-clock reads outside entrypoints.** Every function needing the current time takes `now: datetime`. Only `cli.py` and the `api/` package call `datetime.now(UTC)` — inside `api/`, that's `collect_runner.py` alone; `routes.py` itself reads no clock. This is what makes backoff testable at exact boundaries rather than by sleeping.

**No network access in tests.** Every external call goes through an injected `HttpFetcher` or `CommandRunner`; tests supply fakes backed by committed fixtures. 202 tests run in a few seconds against real Postgres with the network unplugged.

**Every collection operation is idempotent.** Enforced by the database — `uq_items_source_external` plus `ON CONFLICT DO NOTHING` — never by an application-level existence check, which would lose the race between two concurrent collectors.

**Timestamps are timezone-aware UTC.** `TIMESTAMPTZ` columns; adapters coerce naive upstream values before they reach the store.

- **Every endpoint requires a session.** There is no anonymous read. The two
  exceptions are `POST /api/auth/login` and `POST /api/auth/setup`, which are
  how a request acquires a session in the first place.
- **Every table that any code touches has exactly one owning module.** Content
  tables (`items`, `sources`, `subscriptions`, `fetch_runs`, `item_tags`) belong
  to `store.py` for writes and `query.py` for reads. The three auth tables
  (`users`, `sessions`, `invites`) belong to `api/auth.py`. That is eight of the
  nine; `collectors` is declared in `models.py` and deliberately has no owner
  yet, because nothing reads or writes it until Plan 3. `routes.py` builds no
  queries — when `PUT /api/subscriptions/{id}` needed an existence check, it got
  `query.get_source_by_id` rather than a `session.get` in the handler.
- **Accounts are created from a shell, never over HTTP from nothing.** There
  is no signup endpoint. `reachstore invite` issues a one-time link; only
  someone with shell access to this machine can start an account.

---

## 4. Data model

Nine tables. The seven below, plus `sessions` and `invites`, which are described after the table.

| Table | Holds |
|---|---|
| `users` | accounts; `llm_provider` / `llm_key_encrypted` anticipate bring-your-own-key |
| `collectors` | registered collector machines (Plan 3) |
| `sources` | what to collect: `(kind, identifier, tier)`, unique on `(kind, identifier)` |
| `subscriptions` | which user cares about which source; filters reads, never collection |
| `items` | the content; unique on `(source_id, external_id)` |
| `fetch_runs` | one row per source per collection attempt — the source of truth for health |
| `item_tags` | per-user tags on items |

**Sharing model: content is shared, interest is per-user.** `items.owner_user_id IS NULL` means shared; non-null means private to that user. Sources have no owner at all, which is why `source_health` is a global operator view and takes no `user_id`.

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

**Full-text search** uses a generated column:

```sql
content_tsv = setweight(to_tsvector('english', coalesce(title,'')),        'A') ||
              setweight(to_tsvector('english', coalesce(content_text,'')), 'B')
```

Postgres maintains it; SQLAlchemy declares it `Computed(persisted=True)` so it is never written but is usable in queries. GIN-indexed. Weight `A` on titles means title matches outrank body matches — verified by a test whose fixture holds term frequency constant so only the weighting can decide the order.

---

## 5. The adapter contract

Every source type implements one protocol:

```python
class Adapter(Protocol):
    kind: str
    tier: int
    def fetch(self, identifier: str, since: datetime | None) -> list[NormalizedItem]: ...
```

The contract is documented on the protocol itself, because Plan 3 hands it to adapters written against the docstring rather than against these three examples:

- failures raise `AdapterError` and nothing else
- an empty result returns `[]` rather than raising
- `published_at` is timezone-aware UTC or `None`
- `since` is advisory; the orchestrator does not depend on it being honoured

**Current adapters** — all Tier 1, all free, none requiring an API key:

| Kind | Transport | Notes |
|---|---|---|
| `rss` | `HttpFetcher` → feedparser | Prefers `<content:encoded>` over `<description>`; stores the raw XML |
| `github_repo` | `CommandRunner` → `gh api` | Drives the official CLI rather than reimplementing auth and pagination |
| `web_page` | `HttpFetcher` → Jina Reader | `external_id` is a hash of the extracted content, so an unchanged page inserts nothing |

`registry.build_registry(http, runner)` maps `kind` → adapter, keyed off each adapter's own `kind` attribute so the key cannot drift from the implementation.

**Transports are injected.** `HttpxFetcher` and `SubprocessRunner` are the production implementations; both wrap their failures as `AdapterError` so the orchestrator sees one exception type regardless of transport.

---

## 6. Collection

`collect_tier` walks the sources in a tier and calls `collect_source` for each.

**Bulkhead isolation.** `collect_source` never raises. It catches broad `Exception` — not `BaseException`, so Ctrl-C still works — records a failed `fetch_run`, and returns. One broken source cannot stop a run.

The subtle part: a database-level failure inside `upsert_items` aborts the transaction, after which the handler's own `flush()` would raise too. So the fetch-and-store work runs inside `session.begin_nested()` (a SAVEPOINT); a failure rolls back to it and leaves the session usable for recording the failure. The `fetch_run` row is created *before* the savepoint so it survives the rollback.

**`collect_tier` commits after every source, not once at the end of the tier.** Two reasons: progress must be observable while a tier is still running, and a crash mid-tier must keep the failure rows the circuit breaker depends on rather than lose them with an uncommitted transaction. The commit itself is inside the bulkhead — if it fails, the source's result is rewritten from whatever `collect_source` returned to a failure, so the caller never sees a success claim for work the rollback just discarded.

**Backoff and circuit breaker are derived, not stored.** There is no `consecutive_failures` column to drift out of sync — health is computed from `fetch_runs` history on demand. Failures back off exponentially from 15 minutes, capped at 24 hours; five consecutive failures open the breaker. `--force` bypasses both gates, which is how an operator retries a disabled source.

**Exit codes.** `collect` exits 1 only when the tier had at least one source and *every* one failed. Partial failure exits 0 — that is the bulkhead working, and alerting on one flaky source would make the signal worthless.

---

## 7. Web layer

FastAPI over the existing store — endpoints for sources, feed, search, items, catalog, subscriptions, collection, and auth, no SQL of its own; `query.py` remains the only reader. A React + Vite reader in `web/`: a login gate, a feed pane, search, item detail, a subscriptions strip, and a health strip (admin only) showing each source's status and error text. The server refuses to bind off-loopback without an explicit override (§9).

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

`api/deps.py` is a second composition root. Its **module-level engine** (`lru_cache`d) is the one deliberate difference from `cli.py`: a fresh pool per request, built the way `cli.py` builds one per invocation, would exhaust Postgres connections under a server's request rate. `app.assert_loopback` enforces the loopback restriction rather than documenting it; see §9 for why it still matters now that there is authentication.

`POST /api/collect` runs a tier as a FastAPI background task. `collect_runner.try_start()` claims a single in-process run slot synchronously, in the request handler, before the task is scheduled; a second request while one is in flight gets a truthful 409 rather than a background task racing another `collect_tier` over the same connection.

**`collecting`, not a `fetch_runs` read, is the completion signal.** `GET /api/sources` reports `collect_runner.is_running()` directly. It cannot be derived from run status instead: `collect_tier` commits only terminal statuses (§6), so a `running` row is flushed and then overwritten before any commit ever lands — no second connection observes it mid-run. A poll asking "is anything still running?" via `fetch_runs` would see nothing on its first tick and wrongly declare the run finished. The frontend polls `/api/sources` while a run is in flight and stops on the tick where `collecting` goes false.

---

## 8. Development

```bash
docker compose -f docker-compose.dev.yml up -d      # Postgres 16 on :5433
cp .env.example .env
uv venv --python 3.12 .venv                          # system python is 3.9
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/alembic upgrade head
.venv/bin/pytest                                     # 202 tests, a few seconds, offline
```

`TEST_DATABASE_URL` must differ from `DATABASE_URL` and end in `_test`; `conftest.py` refuses to drop a schema otherwise, because it runs `DROP SCHEMA public CASCADE` on every session.

Running the app takes both servers; Vite proxies `/api` to FastAPI so the browser stays same-origin:

```bash
.venv/bin/python -c "from reachstore.api.app import serve; serve()"   # :8000
cd web && npm run dev                                                 # :5173, proxies /api to :8000
```

`serve()` is the supported entrypoint because `assert_loopback` (§7) lives there -- invoking uvicorn
directly bypasses the guard and can bind off-loopback with the session cookie exposed in cleartext
and no CSRF protection or login rate limiting (§9).

---

## 9. Decisions worth knowing

**Postgres, not SQLite.** SQLite's single-writer lock breaks under concurrent collector pushes, which Plan 3 requires by design.

**Drive `gh` rather than call GitHub's API.** The CLI already solves authentication, pagination, rate limits, and API versioning. The cost is a binary dependency; the alternative is reimplementing four solved problems.

**Derived state over stored counters.** A mutable counter is a second copy of a fact the history already contains, and every write path must remember to update it correctly. One missed path and the counter silently disagrees with reality.

**Content-hash identity for web pages.** A page has no natural item id and no reliable date. Hashing the extracted content means an unchanged page conflicts and inserts nothing, while a changed page inserts one new row and keeps the old version as history.

**No CORS anywhere.** Vite proxies `/api` to FastAPI in development; FastAPI serves the built `web/dist` assets in production. Both keep the browser same-origin, so no CORS middleware exists in the codebase at all. If one is ever added, that is a sign a second origin has entered the picture — not a piece that was missing from this one.

**An in-process flag over inferring completion from `fetch_runs`.** The obvious design reads run status to know whether a collection is still going. It doesn't work here: `collect_tier` only ever commits terminal statuses, so no query against `fetch_runs` can observe a run in progress. `collect_runner` tracks it directly with a `threading.Lock`-guarded flag instead — correct because this slice is single-worker by design; multiple uvicorn workers would each get their own copy and need a Postgres advisory lock in its place.

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
- **Emails are normalised to lowercase at every entry point** (`auth.normalize_email`,
  applied in `find_user_by_email`, `create_invite`, and the one place a `users`
  row is written). The reason is the bullet above, not security: the invitee
  never types their address during setup, so they never learn which case the
  operator used, and a case mismatch at the login form returns the deliberately
  identical "incorrect" message. That makes a case-induced lockout impossible
  for the locked-out person *or* the operator to diagnose without a database
  query.
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

**The record of how this was built** is split by plan, both in `docs/superpowers/reviews/`. Plan 1
(core store + Tier-1 collection) — every review finding, ruling, and rationale across 8 tasks and
10 review rounds — is `2026-08-13-core-store-execution-ledger.md` plus `task-1-report.md` through
`task-8-report.md`. The web UI and API layer's equivalent, across its 10 tasks, is
`2026-09-02-web-ui-and-api-progress.md` plus `2026-09-02-web-ui-and-api-task-1-report.md` through
`2026-09-02-web-ui-and-api-task-10-report.md`.
