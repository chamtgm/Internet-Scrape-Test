# Task 8 Report: Catalog and subscriptions

## What I implemented

- `query.CatalogEntry` / `query.catalog(session, *, user_id)` in `src/reachstore/query.py` —
  every source LEFT JOINed against the user's active subscriptions, returning
  `{source_id, kind, identifier, tier, subscribed}`.
- `store.subscribe(session, *, user_id, source_id, now)` and `store.unsubscribe(session, *,
  user_id, source_id)` in `src/reachstore/store.py` — idempotent via `INSERT ... ON CONFLICT
  (uq_subscriptions_user_source) DO UPDATE SET active = True` and a plain `UPDATE ... SET
  active = False` respectively. No read-then-write anywhere.
- `CatalogEntryOut` / `CatalogResponse` schemas in `src/reachstore/api/schemas.py`, mirroring
  `CatalogEntry` with `extra="forbid"`.
- Routes in `src/reachstore/api/routes.py`: `GET /api/catalog` (non-admin, gated only by
  `get_current_user`), `PUT /api/subscriptions/{source_id}` (404s if the source doesn't exist,
  else 204), `DELETE /api/subscriptions/{source_id}` (always 204, even if never subscribed).
- Wired `query.search`'s existing `subscribed_only` parameter through `GET /api/search` — its
  first caller. `GET /api/feed` was **not** touched (`query.feed` has no such parameter; out of
  scope per the task brief).
- Step 9: three fixes to `tests/test_api_permissions.py` (details below).

All imports matched the brief's pre-verified facts exactly (bare `insert`, new `from sqlalchemy
import update`, `Item, Subscription` in store.py, `query, store` and `Item, Source` in
routes.py) — no surprises there.

## TDD evidence

**RED** — `.venv/bin/pytest tests/test_api_subscriptions.py -v`

```
FAILED tests/test_api_subscriptions.py::test_catalog_lists_every_source_with_a_subscribed_flag - KeyError: 'sources'
FAILED tests/test_api_subscriptions.py::test_catalog_reflects_only_the_requesting_users_subscriptions - AssertionError: assert 405 == 204
FAILED tests/test_api_subscriptions.py::test_catalog_omits_health_and_error_fields - KeyError: 'sources'
FAILED tests/test_api_subscriptions.py::test_subscribe_is_idempotent - AssertionError: assert 405 == 204
FAILED tests/test_api_subscriptions.py::test_unsubscribe_is_idempotent_and_works_when_never_subscribed - AssertionError: assert 405 == 204
FAILED tests/test_api_subscriptions.py::test_resubscribing_after_unsubscribing_works - AssertionError: assert 405 == 204
FAILED tests/test_api_subscriptions.py::test_subscribing_to_an_unknown_source_is_404 - AssertionError: assert 405 == 404
FAILED tests/test_api_subscriptions.py::test_search_subscribed_only_filters_by_subscription - AssertionError: assert ['from-b', 'from-a'] == ['from-a']
FAILED tests/test_api_subscriptions.py::test_unsubscribing_removes_items_from_a_subscribed_only_search - AssertionError: [... item present ...] == []
FAILED tests/test_api_subscriptions.py::test_catalog_requires_a_session - AssertionError: assert 404 == 401
FAILED tests/test_api_subscriptions.py::test_subscribing_requires_a_session - AssertionError: assert 405 == 401
========================= 11 failed, 1 passed in 0.80s =========================
```

Expected reasons, confirmed: `/api/catalog` didn't exist (404/KeyError), `/api/subscriptions/*`
didn't exist (405 Method Not Allowed — the router had no PUT/DELETE on that path), and
`subscribed_only` was silently ignored by `get_search` (FastAPI drops undeclared query params),
so the filtered-search tests saw unfiltered results. This is exactly the failure mode the task
brief predicted.

**GREEN** — `.venv/bin/pytest tests/test_api_subscriptions.py -v`

```
tests/test_api_subscriptions.py::test_catalog_lists_every_source_with_a_subscribed_flag PASSED
tests/test_api_subscriptions.py::test_catalog_reflects_only_the_requesting_users_subscriptions PASSED
tests/test_api_subscriptions.py::test_catalog_omits_health_and_error_fields PASSED
tests/test_api_subscriptions.py::test_subscribe_is_idempotent PASSED
tests/test_api_subscriptions.py::test_unsubscribe_is_idempotent_and_works_when_never_subscribed PASSED
tests/test_api_subscriptions.py::test_resubscribing_after_unsubscribing_works PASSED
tests/test_api_subscriptions.py::test_subscribing_to_an_unknown_source_is_404 PASSED
tests/test_api_subscriptions.py::test_search_subscribed_only_filters_by_subscription PASSED
tests/test_api_subscriptions.py::test_subscribed_only_defaults_to_false PASSED
tests/test_api_subscriptions.py::test_unsubscribing_removes_items_from_a_subscribed_only_search PASSED
tests/test_api_subscriptions.py::test_catalog_requires_a_session PASSED
tests/test_api_subscriptions.py::test_subscribing_requires_a_session PASSED
============================== 12 passed in 0.81s ==============================
```

12 of 12, matching the brief's Step 8 expectation exactly.

Also ran the brief's Step 6 empty-body probe before implementing, to confirm the version claim:
`204 b''` — matches (with an unrelated `StarletteDeprecationWarning` about `httpx`/TestClient
that is pre-existing on this stack and does not appear inside the pytest run, which has its own
warning filters).

## Step 9 — the three `test_api_permissions.py` fixes, and a bug I found and fixed in the brief's own code

All three landed:

1. **Route-enumeration test** (`test_every_api_route_is_in_the_matrix`) — added, with the two
   new `CASES` rows (`GET /api/catalog`, `DELETE /api/subscriptions/999999`).
2. **`no_op_collect` fixed** to clear `_running` via `setattr(collect_runner, "_running", False)`
   instead of a bare `None`-returning lambda, matching `run_collection`'s real `finally` block.
3. **Matrix failures now name the role** (`"anon"`/`"user"`/`"admin"`) instead of the `TestClient`
   repr.

**However**, the brief's literal code for fix #1 does not actually catch anything on this
environment, for two independent reasons I found by testing the negative case (removing the two
new `CASES` rows and confirming the enumeration test still passed — it should have failed):

- **Bug A — `create_app().routes` is not flat on this stack.** On the installed
  `fastapi==0.141.1` / `starlette==1.6.0`, `FastAPI.include_router()` wraps the sub-router in an
  opaque `_IncludedRouter` node with no `.path` attribute (verified by direct inspection —
  `app.routes` returned only 4 built-in doc routes plus an `_IncludedRouter` and a `Mount`, never
  any of our 12 `/api/*` endpoints). The brief's loop (`for route in create_app().routes: path =
  getattr(route, "path", "")`) therefore silently skips every real endpoint and the assertion
  passes vacuously, always — proven by deleting the new `CASES` rows and re-running: still green.
  **Fix:** iterate `reachstore.api.routes.router.routes` directly — the actual `APIRouter`
  instance, unaffected by how FastAPI happens to wire it into the app.
- **Bug B — path templates vs. concrete `CASES` paths.** After fixing Bug A, the test correctly
  started finding real routes, but then failed for `/api/items/{item_id}` too (a route that
  predates this task and already has a `CASES` row: `GET /api/items/999999`). A route's `.path`
  is the template (`/api/items/{item_id}`), while `CASES` holds the concrete resolved path used
  in the actual request (`/api/items/999999`); the brief's `path in covered` is plain string
  equality, which never matches a template against a concrete path — only the `?query` stripping
  case was anticipated. **Fix:** match `covered` paths against each route's path template with a
  small regex (`{param}` segments treated as wildcards) instead of exact string membership.

Evidence both fixes are load-bearing, not just correctness-preserving refactors: I ran
`test_every_api_route_is_in_the_matrix` three ways —
1. Brief's literal code, `CASES` with the two new rows → **passes**, but vacuously (0 real routes
   ever inspected).
2. Brief's literal code, `CASES` with the two new rows removed → **still passes** (same
   vacuousness) — this is the proof the literal code doesn't work.
3. My fixed code (Bug A + Bug B fixes), `CASES` rows removed → **fails**, correctly reporting
   `['/api/catalog', '/api/subscriptions/{source_id}']` as missing.
4. My fixed code, `CASES` rows restored → **passes**, for the real reason this time.

I did not silently deviate — the fix is a straightforward, minimal generalization of exactly what
the brief already asked for ("Note `covered` strips the query string... its own path is
`/api/search`" already acknowledges one class of path-format mismatch; I extended the same idea to
path parameters and to reading the actual router instead of the app's wrapped route table). No
behavior outside this one test function changed from the brief's intent.

## Files changed

- `src/reachstore/query.py` — added `CatalogEntry` + `catalog()`, no new imports.
- `src/reachstore/store.py` — added `subscribe()` + `unsubscribe()`; added `from sqlalchemy
  import update`; extended `from reachstore.models import Item` to `Item, Subscription`.
- `src/reachstore/api/schemas.py` — added `CatalogEntryOut` + `CatalogResponse`.
- `src/reachstore/api/routes.py` — extended imports (`query, store`; `CatalogEntryOut,
  CatalogResponse`; `Item, Source, User`); added `subscribed_only` to `get_search`; added
  `get_catalog`, `put_subscription`, `delete_subscription`.
- `tests/test_api_subscriptions.py` — new file, the brief's Step 1 code verbatim (12 tests).
- `tests/test_api_permissions.py` — two new `CASES` rows; new
  `test_every_api_route_is_in_the_matrix` (with the Bug A/B fixes above); `no_op_collect` now
  clears `_running`; matrix assertion labeled by role. Added one import (`re`, stdlib, for the
  template-matching regex).

## Full suite

`.venv/bin/pytest -q` → **202 passed**, 0 warnings, ~5.3s.

Baseline was 187. Delta: +12 (`test_api_subscriptions.py`) + 1 (`test_every_api_route_is_in_the_
matrix`) + 2 (two new parametrized `CASES` rows expand `test_permission_matrix`) = +15 → 202.
Count did not drop; suite stayed warning-free. Also ran with `-W error::DeprecationWarning` as an
extra check — same 202 passed, no warnings promoted to errors.

## Self-review findings

- `routes.py` builds no queries: `grep -n "select(" src/reachstore/api/routes.py` → no matches.
- Tenant isolation: `query.visible_to` is unchanged (still the only place `Item.owner_user_id` is
  filtered); `catalog()` correctly does **not** use it — sources are shared, not owned, and the
  per-user scoping there is the `Subscription.user_id` join condition, which is a different (and
  correctly separate) mechanism from `Item` ownership.
- Clock discipline: `datetime.now(UTC)` appears in `routes.py` (the entrypoint, for
  `put_subscription`'s `now=`) and nowhere in `query.py` or `store.py` — both take `now` as a
  parameter where needed (`store.subscribe`) or don't need it at all (`store.unsubscribe`,
  `query.catalog`).
- `subscribed_only` confirmed absent from `get_feed` (`grep` for `subscribed_only` in
  `routes.py` shows only the three lines inside `get_search`).
- Catalog field set: `test_catalog_omits_health_and_error_fields` passes, and `CatalogEntryOut`'s
  `extra="forbid"` means any accidental future field addition to `CatalogEntry` without a schema
  update fails loudly rather than silently leaking a health/diagnostic field.
- One table, one owning module: `subscriptions` writes only in `store.py`, reads only in
  `query.py`, consistent with every other content table.
- No new dependencies; no CORS changes; nothing touched under `docs/superpowers/specs|plans|
  reviews/`.
- `ruff` is not installed in this venv (`.venv/bin/ruff` → not found), consistent with prior
  tasks' reports; no lint pass run, nothing in the task instructions requires one.

## Concerns

- The Bug A/B findings above are the only notable deviation from the brief's literal text, and
  only inside one test function's internals (not its intent, its `CASES` rows, or its purpose).
  Flagging for the reviewer in case a different FastAPI/Starlette version is used elsewhere in
  this project's history and the vacuous-pass issue doesn't reproduce there — my fix is
  version-agnostic (reads `router.routes` directly rather than depending on `app.routes`'
  internal representation) so it should hold either way, but I want this called out explicitly
  rather than buried in a comment.
- Port 8000 remains held by the unrelated `php` process noted in prior task reports; not touched,
  and no server was started for this task (nothing in the brief required live manual testing).
