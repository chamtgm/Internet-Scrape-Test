# Task 5 Report: The collect endpoint

## What I implemented

Followed the brief verbatim, in order:

1. **`tests/test_api_collect.py`** (new) — the six tests from the brief, unmodified.
2. **`src/reachstore/api/collect_runner.py`** (new) — `is_running()`, `run_collection(tier, force)`, module-level `_running` flag guarded by `_lock`. Opens its own session via `get_session_factory()()`, runs `collect_tier` with a fresh `build_registry(HttpxFetcher(), SubprocessRunner())`, `raw_dir()`, and `datetime.now(UTC)`. Wraps the call in `try/except Exception/finally` so the function never raises and the flag always clears.
3. **`src/reachstore/api/schemas.py`** — added `Field` to the pydantic import; added `collecting: bool = False` to `SourcesResponse` (no `extra="forbid"`, matching the note that it governs output, not input); added `CollectRequest` (`tier: int = Field(..., ge=1, le=3)`, `force: bool = False`) and `CollectResponse` (`started: bool`, `tier: int | None`, `reason: str | None`).
4. **`src/reachstore/api/routes.py`** — added `BackgroundTasks`, `Response` to the `fastapi` import; added `CollectRequest`, `CollectResponse` to the schema import; added `from reachstore.api import collect_runner`; changed `list_sources` to pass `collecting=collect_runner.is_running()`; added `post_collect` (`POST /api/collect`, `status_code=202`), which returns 409 with `started=False` + `reason` by setting `response.status_code` (not raising `HTTPException`) when `collect_runner.is_running()`, otherwise schedules `collect_runner.run_collection` via `background.add_task` and returns `started=True`.

No SQL, no `sqlalchemy.select` import anywhere in `api/` — confirmed via grep. No advisory lock, no retry logic, no progress percentage — the per-process guard and docstring explaining why are exactly as specified and nothing more.

## What I tested and the results

- `tests/test_api_collect.py` — all 6 tests pass in isolation.
- `tests/test_api_collect.py` + `tests/test_api_sources.py` together — 10 passed (the brief's snapshot assumed `test_api_sources.py` had 4 tests at brief-writing time totaling 8; the current repo already has those same 4 tests, so 6 + 4 = 10 — no discrepancy, just an outdated count in the brief).
- Full suite: **115 passed**, zero warnings (109 existing + 6 new = 115, exactly additive as required).

## TDD Evidence

**RED**

Command: `.venv/bin/pytest tests/test_api_collect.py -v`

Failing output (before creating `collect_runner.py`):

```
ERROR collecting tests/test_api_collect.py
ImportError while importing test module '/Users/dev2/Desktop/Testing/tests/test_api_collect.py'.
...
tests/test_api_collect.py:4: in <module>
    from reachstore.api import collect_runner
E   ImportError: cannot import name 'collect_runner' from 'reachstore.api' (/Users/dev2/Desktop/Testing/src/reachstore/api/__init__.py)
1 error in 0.17s
```

This is the expected failure mode (the brief anticipated `ModuleNotFoundError`; pytest's assertion-rewrite import machinery surfaces the equivalent `ImportError: cannot import name 'collect_runner'` since `reachstore.api` itself exists as a package but the submodule does not) — confirms the tests actually exercise code that doesn't exist yet, not a typo or fixture problem.

**GREEN**

Command: `.venv/bin/pytest tests/test_api_collect.py tests/test_api_sources.py -v`

```
tests/test_api_collect.py::test_collect_accepts_and_reports_started PASSED
tests/test_api_collect.py::test_collect_rejects_a_second_run_while_one_is_in_flight PASSED
tests/test_api_collect.py::test_collect_rejects_an_invalid_tier PASSED
tests/test_api_collect.py::test_sources_endpoint_reports_whether_a_run_is_in_flight PASSED
tests/test_api_collect.py::test_the_runner_opens_its_own_session_and_always_clears_the_flag PASSED
tests/test_api_collect.py::test_a_crashing_run_still_clears_the_flag PASSED
tests/test_api_sources.py::test_sources_endpoint_returns_every_source PASSED
tests/test_api_sources.py::test_sources_endpoint_is_empty_when_no_sources PASSED
tests/test_api_sources.py::test_source_status_out_rejects_unexpected_field PASSED
tests/test_api_sources.py::test_source_status_out_requires_every_field PASSED
10 passed in 0.28s
```

Full suite: `.venv/bin/pytest` → `115 passed in 1.68s`, no warnings.

## Files changed

- `src/reachstore/api/collect_runner.py` (new)
- `src/reachstore/api/routes.py` (modified)
- `src/reachstore/api/schemas.py` (modified)
- `tests/test_api_collect.py` (new)

Commit: `fd22511` — "feat: background collection endpoint with a concurrency guard"

## Self-review findings

- **Completeness:** all 7 brief steps done in order; code matches the brief's listings verbatim (checked line by line against the diff).
- **Quality:** `is_running()`'s docstring states the real reason `collecting` can't come from `fetch_run` status (terminal-only commits from Task 4, so a reader never observes "running"). `run_collection`'s docstring explains the own-session requirement (background tasks run after the request session closes) and the per-process guard's scope/limitation (multi-worker uvicorn would need a Postgres advisory lock instead — not built, per instruction).
- **Discipline:** no advisory lock, no retry, no progress percentage, no second endpoint (folded into the existing `/api/sources` poll as directed). `grep -n select src/reachstore/api/*.py` returns nothing — the binding constraint (no `sqlalchemy.select` in the API layer) holds.
- **Testing:** `test_the_runner_opens_its_own_session_and_always_clears_the_flag` asserts `seen["running_during"] is True` (proves the flag is set before `collect_tier` runs) and `collect_runner.is_running() is False` afterward (proves `finally` cleared it). `test_a_crashing_run_still_clears_the_flag` calls a `collect_tier` replacement that raises `RuntimeError` and asserts `run_collection` doesn't propagate it and the flag still clears — this fails if the `finally` block were removed outright. Output is pristine: 115 passed, 0 warnings, 0 skipped.

  **Correction (added after review):** the sentence above originally also claimed the test would fail "if... replaced with a bare post-try assignment that the exception could skip." That half was wrong and has been struck: the `except Exception` clause already catches `RuntimeError`, so a dedented post-`try` assignment (outside `finally` but after the `except`) would still execute on this path and the test would still pass. The test only pins outright deletion of the cleanup, not a `finally`-vs-plain-statement distinction. See the Fix Report below for the coordinator's original wording of this correction and the two real defects the review found.
- No lint/type-check tooling (ruff/mypy) is configured in this project's venv, so none was run beyond pytest.

## Concerns

None. Implementation follows the brief exactly; no deviations were needed.

---

## Fix Report: coordinator review follow-up

The coordinator's review found the spec-compliant implementation still let both failure modes it exists to prevent go through — both defects were in the brief's own code, not a transcription error. Two Important fixes and five one-line Minors. All addressed below.

### Finding 1 (Important) — the guard's answer to the client was wrong

**Bug:** `post_collect` checked `collect_runner.is_running()`, but the flag was only ever set inside `run_collection`, which Starlette runs *after* the response is sent. Between the check and the flag actually being set there is a window (rest of the handler, response serialisation, socket write) during which a second concurrent request also sees no run in flight, also gets 202 `started=True`, and its `run_collection` call is a no-op because the first one had claimed the flag by the time it runs. The frontend has no way to detect the second run never happened — `collecting` just goes True then False once, and the second tier is silently never collected.

**Fix:**
- Added `collect_runner.try_start() -> bool`: atomically claims `_running` under `_lock`. Docstring records that this must be called synchronously by the handler, not from inside `run_collection`, and explicitly accepts the resulting tradeoff — the flag is held from claim until `run_collection` finishes, so a client disconnect or shutdown between response and dispatch leaks the flag until process restart. No staleness timeout added (out of scope, single-user localhost app).
- `run_collection` no longer claims the flag; it only clears it and defensively logs+bails (Minor 3) if invoked without a prior claim.
- `routes.py`'s `post_collect` now calls `if not collect_runner.try_start():` → 409, closing the window: by the time the response is returned, `_running` is already `True`.
- `tests/test_api_collect.py::test_collect_rejects_a_second_run_while_one_is_in_flight` no longer monkeypatches `is_running`; it calls `collect_runner.try_start()` directly (the same primitive the handler uses) to claim the slot for real, then asserts the endpoint 409s.
- Also updated `test_the_runner_opens_its_own_session_and_always_clears_the_flag` and `test_a_crashing_run_still_clears_the_flag`, which call `run_collection` directly: both now call `collect_runner.try_start()` first, matching the new contract that `run_collection` assumes an already-claimed slot.

### Finding 2 (Important) — two paths left `_running` stuck `True`

**Bug 1:** `session = get_session_factory()()` sat outside the `try`. `get_session_factory()` chains to `get_settings()` and `create_engine(...)`, either of which can raise on a missing/malformed `DATABASE_URL`. `lru_cache` doesn't cache exceptions, so it would raise every call, forever — and since this line was before the `try`, the flag (already claimed) would never clear.

**Bug 2:** `finally: session.close(); with _lock: _running = False` ran `close()` before the flag clear. `close()` can itself raise — e.g. returning a connection broken mid-transaction, precisely the aftermath of the DB outage the `except` exists for. If it raised, the flag clear never ran and `run_collection` itself raised, breaking its documented "never raises" contract.

**Fix:** restructured to the coordinator's suggested shape — session acquisition and `collect_tier` sit inside an inner `try`, `session.close()` in that inner `finally`; the outer `except Exception: log.exception(...)` and outer `finally: with _lock: _running = False` wrap all of it, so both a raising `get_session_factory()()` and a raising `close()` still clear the flag and never propagate.

Added `tests/test_api_collect.py::test_a_session_close_that_raises_still_clears_the_flag`: a `FakeSession.close()` that raises `RuntimeError`, with `collect_tier` faked to succeed. Neither pre-existing fake session had a `close()` that could raise, so this is genuinely new coverage.

**Verifying the new tests actually pin these bugs** (not requested by name, but done to back the "TDD evidence" requirement — reverted the fix, confirmed the new test fails for the *right* reason, then restored it):

Isolated Finding 2's exact bug (session opened outside `try`, `close()` before flag clear, `try_start()` kept intact so the test's own claim still worked) into a scratch copy of `collect_runner.py`, then ran:

```
.venv/bin/pytest tests/test_api_collect.py::test_a_session_close_that_raises_still_clears_the_flag -v
```

Failing output confirming the pre-fix ordering lets `close()`'s `RuntimeError` propagate straight out of `run_collection` (violating "never raises") before the flag is ever cleared:

```
FAILED tests/test_api_collect.py::test_a_session_close_that_raises_still_clears_the_flag - RuntimeError: connection already closed
src/reachstore/api/collect_runner.py:48: in run_collection
    session.close()
...
E       RuntimeError: connection already closed
1 failed in 0.25s
```

Restored the fixed file (`diff` against the working tree showed no difference), then re-ran green (see below).

### Minors

1. `import pytest` in the test file — no longer unused: it is now needed for the new `@pytest.fixture(autouse=True)` reset fixture (Minor 2), so it stays.
2. Added `_reset_collect_runner_flag`, an autouse fixture in `tests/test_api_collect.py` that sets `collect_runner._running = False` before and after every test — removes cross-test poisoning, which matters more now that `try_start()` can be called directly by a test without going through a `run_collection` that clears it.
3. Added `log.warning(...)` in `run_collection` on the (now API-unreachable, but caller-bug-reachable) path where it's invoked without a prior `try_start()` claim, so a misuse would be visible in the log rather than silently doing nothing.
4. Added `responses={409: {"model": CollectResponse}}` to the `@router.post("/collect", ...)` decorator so the 409 body shape is in the OpenAPI schema.
5. `test_the_runner_opens_its_own_session_and_always_clears_the_flag`'s `fake_collect_tier` now captures `kwargs["now"]` and the test asserts `seen["now"].tzinfo is UTC`.

### Correction to the original self-review

The original report's testing bullet claimed `test_a_crashing_run_still_clears_the_flag` "fails if the `finally` block were removed or replaced with a bare post-try assignment that the exception could skip." The second half was wrong: `except Exception` already catches the `RuntimeError`, so a dedented post-`try` statement (after the `except`, not in a `finally`) would still execute on this path and the test would still pass. The test only pins outright deletion of the cleanup. Struck and corrected in place above rather than left standing.

### Commands and results

```
.venv/bin/pytest tests/test_api_collect.py tests/test_api_sources.py -v
```
```
tests/test_api_collect.py::test_collect_accepts_and_reports_started PASSED
tests/test_api_collect.py::test_collect_rejects_a_second_run_while_one_is_in_flight PASSED
tests/test_api_collect.py::test_collect_rejects_an_invalid_tier PASSED
tests/test_api_collect.py::test_sources_endpoint_reports_whether_a_run_is_in_flight PASSED
tests/test_api_collect.py::test_the_runner_opens_its_own_session_and_always_clears_the_flag PASSED
tests/test_api_collect.py::test_a_crashing_run_still_clears_the_flag PASSED
tests/test_api_collect.py::test_a_session_close_that_raises_still_clears_the_flag PASSED
tests/test_api_sources.py::test_sources_endpoint_returns_every_source PASSED
tests/test_api_sources.py::test_sources_endpoint_is_empty_when_no_sources PASSED
tests/test_api_sources.py::test_source_status_out_rejects_unexpected_field PASSED
tests/test_api_sources.py::test_source_status_out_requires_every_field PASSED
11 passed in 0.20s
```

Full suite:
```
.venv/bin/pytest
```
```
116 passed in 1.69s
```
Zero warnings (`grep -i warning` on the full-suite output returns nothing).

### Files changed (this fix)

- `src/reachstore/api/collect_runner.py` — added `try_start()`; restructured `run_collection`'s try/except/finally so session acquisition and `close()` are covered by the flag-clearing `finally`; added the dropped-call warning.
- `src/reachstore/api/routes.py` — `post_collect` now calls `try_start()` instead of `is_running()`; added `responses={409: {"model": CollectResponse}}`.
- `tests/test_api_collect.py` — autouse flag-reset fixture; concurrency test now claims the slot for real instead of monkeypatching `is_running`; both direct-invocation tests call `try_start()` first; new `test_a_session_close_that_raises_still_clears_the_flag`; `now` tz-awareness assertion added to the existing session test.

Commit: `5cb03f5` — "fix: atomic collect claim and flag-safe cleanup on failure (task-5 review)"

### Concerns

None outstanding. Both Important findings are structurally closed (verified Finding 2 by reproducing the original failure against an isolated pre-fix copy of the code; Finding 1 is closed by construction — the claim is now synchronous within the request-response cycle, so no interleaving of a second request's check can land inside the old window). All five minors applied. Full suite green with zero warnings at 116 (115 + 1 new test for Finding 2's close()-raises path).
