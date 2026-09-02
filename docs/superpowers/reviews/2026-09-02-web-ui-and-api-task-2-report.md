# Task 2 Report: API foundation and the health endpoint

## What I implemented

Followed `task-2-brief.md` steps 1-11 in order, verbatim.

- `pyproject.toml`: added `fastapi>=0.115` and `uvicorn[standard]>=0.30` to `dependencies`.
- `src/reachstore/api/__init__.py`: empty, marks the package.
- `src/reachstore/api/deps.py`: `get_engine()` (lru_cache'd, one connection pool per process), `get_session_factory()` (lru_cache'd), `get_session()` (FastAPI dependency, closes the session in a `finally`), `raw_dir()`, and `DEFAULT_USER_ID = 1`.
- `src/reachstore/api/schemas.py`: `SourceStatusOut` (mirrors `query.SourceStatus`'s nine fields, same order) and `SourcesResponse`.
- `src/reachstore/api/routes.py`: `GET /api/sources`, built via `query.source_health(session)` and `SourceStatusOut(**vars(s))` for each status — no query construction in the API layer.
- `src/reachstore/api/app.py`: `assert_loopback(host, *, allow_nonlocal)` as a standalone function, `create_app()` (mounts the router, serves `web/dist` as static files only if it exists, `/api/*` routes registered first so they always win), and `serve()` which calls `assert_loopback` before `uvicorn.run`.

I verified every one of the six new/test files matches the brief's code blocks byte-for-byte (diffed programmatically) — no deviation, no typos.

## What I tested and the results

- `tests/test_api_sources.py` — two tests: `test_sources_endpoint_returns_every_source` (inserts a `Source`, asserts identifier/kind/item_count/last_status/error_text on the `sources` list) and `test_sources_endpoint_is_empty_when_no_sources` (asserts `body["sources"] == []`, not whole-response equality, per the brief's Decision 5 — Task 5 will add a `collecting` key to this same response).
- `tests/test_api_app.py` — three tests for `assert_loopback`: loopback hosts (`127.0.0.1`, `localhost`, `::1`) pass silently; `0.0.0.0` raises `RuntimeError` mentioning `REACHSTORE_ALLOW_NONLOCAL`; `0.0.0.0` with `allow_nonlocal=True` passes silently.
- Full suite: 95 passed (90 pre-existing + 5 new), 0 failed, 0 broken.

## TDD Evidence

**RED**

Command: `.venv/bin/pytest tests/test_api_sources.py tests/test_api_app.py -v`

Before any `src/reachstore/api/*` files existed, both test modules failed to collect:

```
ERROR tests/test_api_sources.py - ModuleNotFoundError: No module named 'reachstore.api'
ERROR tests/test_api_app.py - ModuleNotFoundError: No module named 'reachstore.api'
Interrupted: 2 errors during collection
```

This is the expected failure: the tests import `reachstore.api.app` and `reachstore.api.deps`, and that package did not exist yet. Exactly matches the brief's Step 3 expectation.

**GREEN**

Command: `.venv/bin/pytest tests/test_api_sources.py tests/test_api_app.py -v`

After creating `deps.py`, `schemas.py`, `routes.py`, `app.py`:

```
tests/test_api_sources.py::test_sources_endpoint_returns_every_source PASSED [ 20%]
tests/test_api_sources.py::test_sources_endpoint_is_empty_when_no_sources PASSED [ 40%]
tests/test_api_app.py::test_loopback_hosts_are_allowed PASSED [ 60%]
tests/test_api_app.py::test_non_loopback_host_is_refused PASSED [ 80%]
tests/test_api_app.py::test_non_loopback_host_allowed_with_explicit_override PASSED [100%]

5 passed, 1 warning in 0.26s
```

The one warning is `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead` — emitted by the installed `fastapi==0.141.1`/`starlette==1.6.0` on import of `fastapi.testclient`, not by any code written for this task. The brief explicitly says `httpx` is already a dependency and forbids adding a separate test-http dependency, so I left this as-is; see Concerns below.

Full-suite run before committing (`.venv/bin/pytest -q`): **95 passed** in 1.60-1.63s, same single warning, no other warnings, no failures.

## By-hand verification (Step 10)

Port 8000 was already bound by an unrelated local PHP process (`lsof -i :8000` showed `php` listening), so I served on port 8001 instead (`serve(port=8001)`), which is equivalent verification against the real `.env` database.

Command:
```bash
.venv/bin/python -c "from reachstore.api.app import serve; serve(port=8001)" &
sleep 3
curl -s localhost:8001/api/sources
kill %1
```

Actual output:
```json
{"sources":[{"source_id":1,"kind":"rss","identifier":"https://github.blog/feed/","last_status":"success","last_run_at":"2026-08-20T06:24:18.720191Z","consecutive_failures":0,"needs_attention":false,"error_text":null,"item_count":11},{"source_id":2,"kind":"rss","identifier":"https://this-domain-should-not-resolve-zzzzz1234.invalid/feed","last_status":"failed","last_run_at":"2026-08-20T06:24:56.694777Z","consecutive_failures":3,"needs_attention":false,"error_text":"AdapterError: HTTP request failed for https://this-domain-should-not-resolve-zzzzz1234.invalid/feed: [Errno 8] nodename nor servname provided, or not known","item_count":0},{"source_id":3,"kind":"github_repo","identifier":"octocat/Hello-World","last_status":"success","last_run_at":"2026-08-22T07:50:42.613866Z","consecutive_failures":0,"needs_attention":false,"error_text":null,"item_count":0},{"source_id":4,"kind":"github_repo","identifier":"cli/cli","last_status":"success","last_run_at":"2026-08-22T07:50:42.613866Z","consecutive_failures":0,"needs_attention":false,"error_text":null,"item_count":201}]}
```

Server log confirmed loopback-only binding: `Uvicorn running on http://127.0.0.1:8001`, `GET /api/sources HTTP/1.1" 200 OK`.

Real sources, real `item_count` values (including the `cli/cli` GitHub source's 201 items), `last_status`/`error_text` populated from real `fetch_runs` rows — exactly what Step 10 expects.

## Files changed

- `/Users/dev2/Desktop/Testing/pyproject.toml` (modified — two new dependencies)
- `/Users/dev2/Desktop/Testing/src/reachstore/api/__init__.py` (new)
- `/Users/dev2/Desktop/Testing/src/reachstore/api/deps.py` (new)
- `/Users/dev2/Desktop/Testing/src/reachstore/api/schemas.py` (new)
- `/Users/dev2/Desktop/Testing/src/reachstore/api/routes.py` (new)
- `/Users/dev2/Desktop/Testing/src/reachstore/api/app.py` (new)
- `/Users/dev2/Desktop/Testing/tests/test_api_sources.py` (new)
- `/Users/dev2/Desktop/Testing/tests/test_api_app.py` (new)

Commit: `88b2917` — "feat: FastAPI foundation, loopback guard, and the sources endpoint"

## Self-review findings

- Diffed all six brief-specified files against the actual written files programmatically: byte-for-byte match, no typos or deviations.
- Grepped `src/reachstore/api/` for `select`/`sqlalchemy` imports: only `Session`, `Engine`, and `sessionmaker` types are imported (for type hints and session construction) — no `select()` is built anywhere in the API layer, satisfying the binding constraint. All reads go through `query.source_health`.
- `SourceStatusOut` field order (`source_id, kind, identifier, last_status, last_run_at, consecutive_failures, needs_attention, error_text, item_count`) matches `query.SourceStatus`'s field order exactly, confirmed by reading `query.py` directly.
- No CORS middleware added (per Decision 4).
- `get_engine`/`get_session_factory` left public, no leading underscore (per Decision 1).
- `lru_cache` on `get_engine`/`get_session_factory` kept as-is (per Decision 2).
- `assert_loopback` kept as a standalone, directly-testable function (per Decision 3).
- No files grew beyond what the brief specified — `deps.py`, `schemas.py`, `routes.py`, `app.py` are each exactly the brief's code, nothing added.
- `git status` is clean after commit; no stray `__pycache__` or lockfile changes were staged.

## Concerns

- One pre-existing `StarletteDeprecationWarning` (`httpx` with `starlette.testclient` deprecated in favor of `httpx2`) surfaces from the installed `fastapi==0.141.1`/`starlette==1.6.0` versions resolved by `fastapi>=0.115`. It is not caused by any code in this task, and the brief explicitly forbids adding a separate test-HTTP dependency to work around it ("httpx is already a dependency... no separate test dependency is required"). Flagging for whoever owns dependency pinning going forward — a future `httpx2` migration or a pin on an older `fastapi`/`starlette` would silence it, but that's out of scope for this task.
- Port 8000 was occupied by an unrelated local `php` process during Step 10 verification, so I verified on port 8001 instead via `serve(port=8001)` — this exercises identical code paths (`assert_loopback` with the default host, `create_app`, the real `.env` database) and is not a gap in verification.

---

## Fix report (review follow-up)

Two findings from the Task 2 review, both ruled into scope by the coordinator.

### Finding 1 (Important): SourceStatusOut silently dropped extra fields

`SourceStatusOut` had no `model_config`, so it inherited pydantic v2's default `extra="ignore"`. The brief's claim ("a field is added to one and not the other raises at construction") is only true for a *missing* field — pydantic always requires declared fields regardless of the `extra` setting. It is false for an *added* field: `SourceStatusOut(**vars(s))` would silently drop any new key on `query.SourceStatus` with no matching model field, which is exactly the drift the claim was meant to catch.

**Fix:** added `model_config = ConfigDict(extra="forbid")` to `SourceStatusOut` only (not `SourcesResponse`, which is built with an explicit keyword argument, not a splat). `src/reachstore/api/schemas.py`.

**Covering tests**, added to `tests/test_api_sources.py`:
- `test_source_status_out_rejects_unexpected_field` — constructs `SourceStatusOut(**VALID_SOURCE_STATUS_KWARGS, extra_field="unexpected")`, asserts `pydantic.ValidationError`.
- `test_source_status_out_requires_every_field` — constructs `SourceStatusOut(source_id=1, kind="rss")` (missing fields), asserts `ValidationError`.

**RED** (before the `ConfigDict(extra="forbid")` fix):

Command: `.venv/bin/pytest tests/test_api_sources.py -v`

```
tests/test_api_sources.py::test_sources_endpoint_returns_every_source PASSED [ 25%]
tests/test_api_sources.py::test_sources_endpoint_is_empty_when_no_sources PASSED [ 50%]
tests/test_api_sources.py::test_source_status_out_rejects_unexpected_field FAILED [ 75%]
tests/test_api_sources.py::test_source_status_out_requires_every_field PASSED [100%]

_______________ test_source_status_out_rejects_unexpected_field ________________
>       with pytest.raises(ValidationError):
E       Failed: DID NOT RAISE ValidationError

1 failed, 3 passed, 1 warning in 0.28s
```

This confirms the review finding precisely: the "missing field" direction already worked (pydantic's baseline behavior), only the "extra field" direction was broken under `extra="ignore"`.

**GREEN** (after adding `model_config = ConfigDict(extra="forbid")`):

Command: `.venv/bin/pytest tests/test_api_sources.py tests/test_api_app.py -v`

```
tests/test_api_sources.py::test_sources_endpoint_returns_every_source PASSED [ 14%]
tests/test_api_sources.py::test_sources_endpoint_is_empty_when_no_sources PASSED [ 28%]
tests/test_api_sources.py::test_source_status_out_rejects_unexpected_field PASSED [ 42%]
tests/test_api_sources.py::test_source_status_out_requires_every_field PASSED [ 57%]
tests/test_api_app.py::test_loopback_hosts_are_allowed PASSED [ 71%]
tests/test_api_app.py::test_non_loopback_host_is_refused PASSED [ 85%]
tests/test_api_app.py::test_non_loopback_host_allowed_with_explicit_override PASSED [100%]

7 passed in 0.17s
```

(Note: this run already shows zero warnings because Fix 2, below, was applied by this point.)

### Finding 2 (Minor): non-pristine StarletteDeprecationWarning

`fastapi.testclient` imports `starlette.testclient`, which warns on import that the installed `httpx`-backed client is deprecated in favor of `httpx2`. Per the coordinator's explicit ruling, `httpx2` is not to be installed — `httpx` is production code (`HttpxFetcher` in `src/reachstore/adapters/base.py`) and adding a second HTTP client library to silence a test-only warning is the wrong trade.

**Fix:** added a `filterwarnings` entry to `[tool.pytest.ini_options]` in `pyproject.toml`, scoped by the warning's exact message text, with a comment explaining why.

First attempt used `DeprecationWarning` as the category and did **not** suppress the warning — inspecting `.venv/lib/python3.12/site-packages/starlette/testclient.py` showed the actual class is `starlette.exceptions.StarletteDeprecationWarning`, which subclasses `UserWarning`, not `DeprecationWarning` (Starlette does this deliberately so the warning is visible by default). Corrected the filter's category to `starlette.exceptions.StarletteDeprecationWarning`:

```toml
filterwarnings = [
    # fastapi.testclient warns on import that httpx-backed starlette.testclient is
    # deprecated in favor of httpx2. httpx is production code (HttpxFetcher in
    # adapters/base.py); adding a second HTTP client library to silence a
    # test-only warning is the worse trade, so this is suppressed by exact
    # message instead.
    "ignore:Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.:starlette.exceptions.StarletteDeprecationWarning",
]
```

Verification command: `.venv/bin/pytest tests/test_api_sources.py tests/test_api_app.py`

Output (no warnings summary at all):

```
============================= test session starts ==============================
collected 7 items

tests/test_api_sources.py::test_sources_endpoint_returns_every_source PASSED
tests/test_api_sources.py::test_sources_endpoint_is_empty_when_no_sources PASSED
tests/test_api_sources.py::test_source_status_out_rejects_unexpected_field PASSED
tests/test_api_sources.py::test_source_status_out_requires_every_field PASSED
tests/test_api_app.py::test_loopback_hosts_are_allowed PASSED
tests/test_api_app.py::test_non_loopback_host_is_refused PASSED
tests/test_api_app.py::test_non_loopback_host_allowed_with_explicit_override PASSED

7 passed in 0.17s
```

The filter is scoped to this one warning's exact message and category — no blanket `ignore` that could mask an unrelated warning in future tests.

### Full suite

Command: `.venv/bin/pytest -q`

```
97 passed in 1.58s
```

(90 pre-existing + 5 from the original Task 2 commit + 2 new schema-validation tests = 97. No warnings summary, no failures.)

### Files changed (this fix)

- `/Users/dev2/Desktop/Testing/pyproject.toml` — `filterwarnings` entry added.
- `/Users/dev2/Desktop/Testing/src/reachstore/api/schemas.py` — `model_config = ConfigDict(extra="forbid")` added to `SourceStatusOut`, with a docstring explaining why.
- `/Users/dev2/Desktop/Testing/tests/test_api_sources.py` — two new tests plus a shared `VALID_SOURCE_STATUS_KWARGS` fixture dict.

Commit: `3920f4a` — "fix: forbid extra fields on SourceStatusOut, silence known testclient warning"
