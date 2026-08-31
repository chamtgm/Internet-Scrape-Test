# reachstore — Architecture

**Living document.** Updated as the system changes. Last updated 2026-08-31.

A persistent knowledge store: it collects content from other sites, stores it raw, and searches it at query time. Built on [Agent-Reach](https://github.com/Panniantong/Agent-Reach), which supplies installation and credentials for the upstream tools; reachstore supplies the persistence Agent-Reach lacks.

**Status:** Plan 1 (core store + Tier-1 collection) is shipped and running. The web UI and JSON API are designed and about to be built. Plans for collectors and deployment remain unwritten.

---

## 1. The one idea

**Store raw, judge relevance at query time.** Filtering at ingest is an irreversible decision made with the least information available — you cannot recover an item you declined to store. So collection is deliberately indiscriminate and every judgement happens on read.

Two consequences run through the whole design: ingestion must be *idempotent* (safe to re-run forever without duplicating), and the raw upstream payload is kept on disk so a future parser change can reprocess history without re-scraping.

---

## 2. Layers

Each layer depends only on those below it.

```
        cli.py            api/  (planned)          ← entrypoints; the only clock readers
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
              models.py                            ← 7 tables, Postgres 16
```

| Module | Responsibility | Rule |
|---|---|---|
| `models.py` | SQLAlchemy models, 7 tables | `TIMESTAMPTZ` throughout; `content_tsv` is a generated column |
| `store.py` | **The only writer of items** | Idempotent via `ON CONFLICT DO NOTHING` |
| `query.py` | **The only reader** | Owns `visible_to`, the sole tenant predicate |
| `adapters/` | One platform each | Never import `sqlalchemy`; all I/O injected |
| `collect.py` | Orchestration, isolation, backoff | Builds no SQL; calls `store` and `query` |
| `cli.py` | Composition root | Constructs real dependencies; reads the clock |

---

## 3. Invariants

These are enforced, not aspirational. Every one was verified tree-wide by the Plan 1 final review.

**All SQL lives in `store.py` and `query.py`.** No other module imports `sqlalchemy.select` or builds a query. When `collect.py` needed three queries, they were added to `query.py` rather than inlined — the constraint won over the reference implementation.

**The tenant predicate appears in exactly one function.** `query.visible_to(user_id)` returns `owner_user_id IS NULL OR owner_user_id = :user_id`. `get_item`, `feed`, and `search` all call it; none re-expresses it. This is the security boundary of a multi-tenant store, and a second copy is how it erodes.

**No wall-clock reads outside entrypoints.** Every function needing the current time takes `now: datetime`. Only `cli.py` — and, once built, `api/routes.py` — calls `datetime.now(UTC)`. This is what makes backoff testable at exact boundaries rather than by sleeping.

**No network access in tests.** Every external call goes through an injected `HttpFetcher` or `CommandRunner`; tests supply fakes backed by committed fixtures. 86 tests run in 1.5 seconds against real Postgres with the network unplugged.

**Every collection operation is idempotent.** Enforced by the database — `uq_items_source_external` plus `ON CONFLICT DO NOTHING` — never by an application-level existence check, which would lose the race between two concurrent collectors.

**Timestamps are timezone-aware UTC.** `TIMESTAMPTZ` columns; adapters coerce naive upstream values before they reach the store.

---

## 4. Data model

Seven tables.

| Table | Holds |
|---|---|
| `users` | accounts; `llm_provider` / `llm_key_encrypted` anticipate bring-your-own-key |
| `collectors` | registered collector machines (Plan 3) |
| `sources` | what to collect: `(kind, identifier, tier)`, unique on `(kind, identifier)` |
| `subscriptions` | which user cares about which source — **no write path yet** |
| `items` | the content; unique on `(source_id, external_id)` |
| `fetch_runs` | one row per source per collection attempt — the source of truth for health |
| `item_tags` | per-user tags on items |

**Sharing model: content is shared, interest is per-user.** `items.owner_user_id IS NULL` means shared; non-null means private to that user. Sources have no owner at all, which is why `source_health` is a global operator view and takes no `user_id`.

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

**Backoff and circuit breaker are derived, not stored.** There is no `consecutive_failures` column to drift out of sync — health is computed from `fetch_runs` history on demand. Failures back off exponentially from 15 minutes, capped at 24 hours; five consecutive failures open the breaker. `--force` bypasses both gates, which is how an operator retries a disabled source.

**Exit codes.** `collect` exits 1 only when the tier had at least one source and *every* one failed. Partial failure exits 0 — that is the bulkhead working, and alerting on one flaky source would make the signal worthless.

---

## 7. Web layer (planned)

Designed in `docs/superpowers/specs/2026-08-31-web-ui-and-api-design.md`; not yet built.

FastAPI over the existing store — five endpoints, no SQL of its own. A React + Vite two-pane reader: item list left, full stored text right. No authentication in this slice; the server refuses to bind off-loopback without an explicit override.

Two points of note. `api/deps.py` becomes a second composition root with a **module-level engine**, because `cli.py`'s per-call `make_engine` would exhaust the connection pool under a server's request rate. And `DEFAULT_USER_ID` is defined once and passed to every `query` call, so the tenant path stays exercised and Plan 2 replaces a constant rather than threading a new parameter through every call site.

---

## 8. Development

```bash
docker compose -f docker-compose.dev.yml up -d      # Postgres 16 on :5433
cp .env.example .env
uv venv --python 3.12 .venv                          # system python is 3.9
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/alembic upgrade head
.venv/bin/pytest                                     # 86 tests, ~1.5s, offline
```

`TEST_DATABASE_URL` must differ from `DATABASE_URL` and end in `_test`; `conftest.py` refuses to drop a schema otherwise, because it runs `DROP SCHEMA public CASCADE` on every session.

---

## 9. Decisions worth knowing

**Postgres, not SQLite.** SQLite's single-writer lock breaks under concurrent collector pushes, which Plan 3 requires by design.

**Drive `gh` rather than call GitHub's API.** The CLI already solves authentication, pagination, rate limits, and API versioning. The cost is a binary dependency; the alternative is reimplementing four solved problems.

**Derived state over stored counters.** A mutable counter is a second copy of a fact the history already contains, and every write path must remember to update it correctly. One missed path and the counter silently disagrees with reality.

**Content-hash identity for web pages.** A page has no natural item id and no reliable date. Hashing the extracted content means an unchanged page conflicts and inserts nothing, while a changed page inserts one new row and keeps the old version as history.

**The record of how this was built** — every review finding, ruling, and rationale across 8 tasks and 10 review rounds — is in `docs/superpowers/reviews/`.
