# Task 5 report: Require authentication on every existing endpoint

## What was implemented

- `src/reachstore/api/routes.py`:
  - `GET /api/sources` and `POST /api/collect` now depend on `require_admin` (parameter named `_admin`, unused by design — 403 for a non-admin, dependency still runs for its side effect).
  - `GET /api/feed`, `GET /api/search`, `GET /api/items/{item_id}` now depend on `get_current_user` (parameter `user`) and pass `user_id=user.id` to `query.feed` / `query.search` / `query.get_item`, replacing the three `user_id=DEFAULT_USER_ID` call sites.
  - Import changed from `from reachstore.api.deps import DEFAULT_USER_ID, get_session` to `from reachstore.api.deps import get_session`; `require_admin` added to the `reachstore.api.auth` import.
  - `get_one_item`'s docstring updated to drop the "once Plan 2 introduces real users" clause (that has now happened).
  - `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` were **not touched** — confirmed via `git diff` showing no hunks in that region.
- `src/reachstore/api/deps.py`: deleted `DEFAULT_USER_ID = 1` and its docstring. (One incidental fix: the removal originally left zero blank lines before `@lru_cache def get_engine`; restored to the required two blank lines between top-level definitions.)
- New test files (added verbatim from the brief, not modified):
  - `tests/test_api_permissions.py` — anon/user/admin status-code matrix across `/api/feed`, `/api/search`, `/api/items/999999`, `/api/sources`, `/api/auth/me`, `/api/auth/logout`; `test_collect_is_admin_only`; `test_an_unknown_cookie_is_401_not_500`; `test_default_user_id_is_gone`.
  - `tests/test_api_tenant_http.py` — tenant isolation proven through HTTP for `/api/feed`, `/api/items/{id}`, `/api/search`.

## TDD evidence

**RED** — `.venv/bin/pytest tests/test_api_permissions.py tests/test_api_tenant_http.py -v`, run before touching `routes.py`/`deps.py`:

```
FAILED test_permission_matrix[GET-/api/feed-401-200-200] - expected 401, got 200
FAILED test_permission_matrix[GET-/api/search?q=anything-401-200-200] - expected 401, got 200
FAILED test_permission_matrix[GET-/api/items/999999-401-404-404] - expected 401, got 404
FAILED test_permission_matrix[GET-/api/sources-401-403-200] - expected 401, got 200
FAILED test_collect_is_admin_only - assert 202 == 401
FAILED test_an_unknown_cookie_is_401_not_500 - assert 200 == 401
FAILED test_default_user_id_is_gone - assert not True (DEFAULT_USER_ID still present)
FAILED test_private_items_are_invisible_to_other_users - assert {'public'} == {'public', 'alices'}
FAILED test_another_users_item_is_404_not_403 - IndexError: list index out of range
FAILED test_search_is_also_isolated - assert 0 == 1
10 failed, 2 passed in 1.10s
```

The 2 passes were the `GET /api/auth/me` and `POST /api/auth/logout` matrix rows — already gated by Task 4, exactly as expected. Every failure matches the brief's predicted reason: anonymous requests still got 200 because no endpoint required auth yet, every user saw every item because every route still passed the hard-coded user 1, and `deps.DEFAULT_USER_ID` still existed.

**GREEN** — same command, after applying the dependency changes:

```
tests/test_api_permissions.py::test_permission_matrix[GET-/api/feed-401-200-200] PASSED
tests/test_api_permissions.py::test_permission_matrix[GET-/api/search?q=anything-401-200-200] PASSED
tests/test_api_permissions.py::test_permission_matrix[GET-/api/items/999999-401-404-404] PASSED
tests/test_api_permissions.py::test_permission_matrix[GET-/api/sources-401-403-200] PASSED
tests/test_api_permissions.py::test_permission_matrix[GET-/api/auth/me-401-200-200] PASSED
tests/test_api_permissions.py::test_permission_matrix[POST-/api/auth/logout-401-200-200] PASSED
tests/test_api_permissions.py::test_collect_is_admin_only PASSED
tests/test_api_permissions.py::test_an_unknown_cookie_is_401_not_500 PASSED
tests/test_api_permissions.py::test_default_user_id_is_gone PASSED
tests/test_api_tenant_http.py::test_private_items_are_invisible_to_other_users PASSED
tests/test_api_tenant_http.py::test_another_users_item_is_404_not_403 PASSED
tests/test_api_tenant_http.py::test_search_is_also_isolated PASSED
12 passed in 1.13s
```

## Full suite

`.venv/bin/pytest -q`:

```
171 passed in 4.14s
```

Baseline was 159. 159 + 12 new tests = 171. No warnings (project's `pyproject.toml` already suppresses the one expected `httpx`/`starlette.testclient` deprecation via `filterwarnings`; confirmed that suppression is pre-existing, not something I added).

## The 18 retrofitted tests — confirmed untouched

`.venv/bin/pytest tests/test_api_read.py tests/test_api_sources.py tests/test_api_collect.py -v` → **18 passed**, all using `user_client` (reads) or `admin_client` (sources/collect) as Task 3 already set up. `git diff --stat -- tests/test_api_read.py tests/test_api_sources.py tests/test_api_collect.py` produced **no output** — these three files were never touched by this task, confirming zero edits were needed anywhere, not just to assertions.

## Scoped grep

```
$ grep -rn "DEFAULT_USER_ID" src/ tests/ web/src/ || echo "clean"
tests/test_api_permissions.py:65:    assert not hasattr(deps, "DEFAULT_USER_ID")
```

Exactly the one expected surviving reference — the test asserting the constant is gone. No hit in `src/`. (Per instructions, did not grep `docs/`; did not touch `docs/superpowers/specs|plans|reviews` or `docs/architecture.md`.)

## Files changed

- `src/reachstore/api/routes.py` (modified)
- `src/reachstore/api/deps.py` (modified)
- `tests/test_api_permissions.py` (new)
- `tests/test_api_tenant_http.py` (new)

## Self-review findings

- All five target endpoints gated correctly per the access table; `DEFAULT_USER_ID` deleted along with its docstring.
- Both new test files written verbatim from the brief — no assertions altered.
- The three Task-4 auth endpoints (`/auth/login`, `/auth/logout`, `/auth/me`) have zero diff hunks touching them.
- No historical docs touched; grep scoped to `src/`, `tests/`, `web/src/` only as instructed.
- `routes.py` still builds no queries and still contains no `select(` — verified by reading the full diff, only dependency/parameter changes were made.
- One thing I fixed beyond the brief's literal instructions: deleting the `DEFAULT_USER_ID` block left `from reachstore.db import ...` immediately followed by `@lru_cache` with zero blank lines, breaking the two-blank-line convention used for every other top-level definition in the file. Restored it — a one-line formatting fix, not a behavior change.
- Ran `-W error` as an extra check out of caution; it surfaced the `StarletteDeprecationWarning` for `httpx`/`starlette.testclient`, but that warning is pre-existing across the whole suite (feed/read/sources/collect tests that predate this task hit it too) and is deliberately suppressed by an existing `filterwarnings` entry in `pyproject.toml` with a comment explaining why. Not introduced by this task; the project's actual `pytest -q` invocation (no `-W error` override) stays warning-free at 171 passed.

## Concerns

None. The brief's assumptions about the codebase (import shape, docstrings, retrofitted-test client choices) all matched exactly what was in the repository, so no deviation from the brief was needed.
