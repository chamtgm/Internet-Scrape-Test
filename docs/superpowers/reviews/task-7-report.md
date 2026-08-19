# Task 7 Report: Collection orchestration with failure isolation

## What I implemented

- `src/reachstore/collect.py` (new): `CollectResult`, `consecutive_failures`,
  `should_attempt`, `collect_source`, `collect_tier`, and module constants
  `FAILURE_LIMIT = 5`, `BASE_BACKOFF = timedelta(minutes=15)`,
  `MAX_BACKOFF = timedelta(hours=24)`.
- `src/reachstore/query.py` (appended): `SourceStatus`, `source_health`, plus three
  new query helper functions — `recent_fetch_statuses`, `last_run_started_at`,
  `sources_by_tier` — added beyond the brief's Step 4 text to keep all SQL out of
  `collect.py` (see "Deviation" section below).
- `tests/test_collect.py` (new): the brief's 10 tests verbatim, plus 2 additional
  tests (one required by ruling 2, one for backoff boundary correctness).

## TDD Evidence

### RED

Command: `.venv/bin/pytest tests/test_collect.py -v`

Before any implementation existed, with only the test file written:

```
============================= test session starts ==============================
collecting ... collected 0 items / 1 error

==================================== ERRORS ====================================
____________________ ERROR collecting tests/test_collect.py ____________________
ImportError while importing test module '/Users/dev2/Desktop/Testing/tests/test_collect.py'.
Traceback:
tests/test_collect.py:6: in <module>
    from reachstore.collect import (
E   ModuleNotFoundError: No module named 'reachstore.collect'
=========================== short test summary info ============================
ERROR tests/test_collect.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
=============================== 1 error in 0.08s ===============================
```

This is the expected failure per the brief's Step 2 — the module doesn't exist yet,
so nothing under test could have accidentally already passed.

### GREEN

Command: `.venv/bin/pytest tests/test_collect.py -v`

After implementing `collect.py` and appending `source_health`/`SourceStatus` to
`query.py`:

```
collected 12 items

tests/test_collect.py::test_successful_collection_stores_items_and_records_run PASSED
tests/test_collect.py::test_failing_adapter_records_failed_run_and_does_not_raise PASSED
tests/test_collect.py::test_one_failing_source_does_not_abort_the_run PASSED
tests/test_collect.py::test_collect_tier_only_touches_matching_tier PASSED
tests/test_collect.py::test_collect_tier_skips_kinds_with_no_adapter PASSED
tests/test_collect.py::test_consecutive_failures_counts_only_the_recent_streak PASSED
tests/test_collect.py::test_backoff_blocks_retry_immediately_after_failure PASSED
tests/test_collect.py::test_should_attempt_at_exact_backoff_boundary PASSED
tests/test_collect.py::test_circuit_breaker_opens_after_five_consecutive_failures PASSED
tests/test_collect.py::test_force_overrides_the_circuit_breaker PASSED
tests/test_collect.py::test_source_health_reports_attention_state PASSED
tests/test_collect.py::test_collect_tier_isolates_non_adapter_error_and_continues_with_next_source PASSED

============================== 12 passed in 0.22s ==============================
```

(12 = the brief's 10 + `test_collect_tier_isolates_non_adapter_error_and_continues_with_next_source`
required by ruling 2 + `test_should_attempt_at_exact_backoff_boundary` added for
boundary coverage — see below.)

## Full-suite result before committing

Command: `.venv/bin/pytest`

```
============================== 59 passed in 0.30s ==============================
```

59 = 47 pre-existing (Tasks 1–6) + 10 from the brief's Step 1 + 2 additional tests
I added (isolation-for-non-AdapterError, and exact-boundary backoff). No warnings
in the output (`grep -i warning` over the full run output found none).

## Files changed

- `src/reachstore/collect.py` — new
- `src/reachstore/query.py` — modified (appended `recent_fetch_statuses`,
  `last_run_started_at`, `sources_by_tier`, `SourceStatus`, `source_health`)
- `tests/test_collect.py` — new
- `src/reachstore/store.py`, `src/reachstore/models.py`, adapters, registry —
  untouched (verified with `git diff --stat`)

Commit: `911ea8f` — "feat: collection orchestration with failure isolation and
derived health"

## How I handled the two rulings

**Ruling 1 (catch broad `Exception`, not only `AdapterError`):** The brief's own
Step 3 reference implementation already used `except Exception as exc:` in
`collect_source` — no widening was needed there. I did make one deviation beyond
the brief's literal text: the brief's reference sets `run.error_text = str(exc)`
and returns `CollectResult(..., str(exc))`. The ruling explicitly says to "record
the failure with the exception's type and message in `error_text`" — `str(exc)`
alone loses the type (e.g. `KeyError("x")` stringifies to `"'x'"`, with no mention
of `KeyError`). I changed this to `f"{type(exc).__name__}: {exc}"`, e.g.
`"KeyError: 'x'"`. This is still a superstring of what the brief's own test
`test_failing_adapter_records_failed_run_and_does_not_raise` checks (`"feed is
gone" in result.error_text`), so no existing assertion needed to change.

**Ruling 2 (test for a non-`AdapterError` failure):** Added
`test_collect_tier_isolates_non_adapter_error_and_continues_with_next_source` in
`tests/test_collect.py`. It runs `collect_tier` (not just `collect_source`) over
two sources of different kinds — one adapter raises a bare `KeyError`, the other
succeeds — and asserts: `collect_tier` returns both results in source-id order,
the bad source's result and its persisted `fetch_runs` row both show `status ==
"failed"` with `"KeyError"` captured in `error_text`, and the second source's
result and `fetch_runs` row both show `status == "success"`. (Two sources of
different `kind` were required because `collect_tier`'s `registry` is keyed by
`kind`, so two same-kind sources can't be given independently-behaving stub
adapters within a single `collect_tier` call.)

## Deviation from the brief: SQL moved out of `collect.py`

This is the one substantive deviation from the brief's Step 3 reference code, and
I want to flag it clearly since it changes the shape of the solution.

The brief's Step 3 code block imports `from sqlalchemy import desc, select` into
`collect.py` and issues raw `select(...)` statements directly inside
`consecutive_failures`, `should_attempt`, `_last_success_at`, and `collect_tier`'s
source lookup. This directly contradicts the binding Global Constraint I was given
for this task: *"All SQL lives in `store.py` and `query.py`. `collect.py` must not
import `sqlalchemy` or write any SQL — it orchestrates by calling
`store.upsert_items` and `query` functions. Anything requiring a query goes into
`query.py`."* — restated verbatim in the self-review checklist ("No SQL in
`collect.py`: does it import `sqlalchemy` or `select`? It must not.").

I resolved this the same way ruling 1 tells me to resolve the exception-catching
gap: treat the brief's code block as a reference to adapt, not verbatim
requirements (the task instructions reserve "verbatim" for constants, function
signatures, test code, and file paths — not implementation bodies), and follow the
explicit, repeated global constraint instead. Concretely:

- Added three new functions to `query.py`: `recent_fetch_statuses(session,
  source_id, limit) -> list[str]`, `last_run_started_at(session, source_id,
  status) -> datetime | None`, and `sources_by_tier(session, tier) -> list[Source]`.
  Each wraps exactly one `select(...)` statement — the same statements that were
  in the brief's `collect.py` reference, just relocated.
- `collect.py` now calls `query.recent_fetch_statuses`, `query.last_run_started_at`,
  and `query.sources_by_tier` instead of building `select()` statements itself.
  `collect.py` no longer imports `sqlalchemy`'s query-building API at all.
- `collect.py` still imports `Session` from `sqlalchemy.orm` — for the type hint
  only, matching every other module in the codebase (`store.py`, `query.py`) that
  needs to type a session parameter. I judged this consistent with the intent of
  the constraint (no query construction / no SQL execution in `collect.py`), not a
  violation of it, and I'm flagging the judgment call explicitly here rather than
  making it silently.
- All function names, signatures, and public behavior listed in the brief's
  "Interfaces" section (`consecutive_failures(session, source_id) -> int`,
  `should_attempt(session, source_id, now) -> bool`, etc.) are unchanged — only
  where the SQL executes moved.
- This does not introduce a circular import: `query.py` never imports `collect.py`
  at module level (only inside `source_health`'s function body, per the brief's
  own Step 4 note), so `collect.py` importing `reachstore.query` at module level
  is a one-directional dependency. Verified directly: `python -c "import
  reachstore.collect"`, `python -c "import reachstore.query"`, and `python -c
  "from reachstore.query import source_health"` all succeed cleanly.
- Behavior is unchanged: all 10 of the brief's tests, plus my 2 additional tests,
  pass identically before and after this refactor (I ran the suite both ways).

If this reading of the constraint is wrong, the fix is mechanical (inline the
three `query.py` helpers back into `collect.py` and restore the `sqlalchemy`
import) — flagging it here rather than guessing silently, per "ask now if a wrong
assumption would be expensive."

One additional small deviation: the brief's reference `collect.py` imports `Item`
from `reachstore.models` but never uses it. I omitted that unused import.

## Self-review findings

- **Completeness:** All produced interfaces from the brief's "Produces" list exist
  with the exact signatures specified: `CollectResult`, `consecutive_failures`,
  `should_attempt`, `collect_source`, `collect_tier`, `FAILURE_LIMIT`,
  `BASE_BACKOFF`, `MAX_BACKOFF`, `query.source_health`, `SourceStatus`.
- **Isolation — traced every branch of `collect_source`:**
  - Object construction (`FetchRun(...)`), `session.add`, and the return
    statements are pure Python — cannot raise.
  - The `try` block (`query.last_run_started_at`, `adapter.fetch`,
    `upsert_items`) is fully covered by `except Exception`, satisfying ruling 1.
    `KeyboardInterrupt`/`SystemExit` are `BaseException` subclasses (not
    `Exception` subclasses), so they still propagate, as required.
  - **Known, unfixed gap (present in the brief's own reference design too):** the
    initial `session.flush()` (before the `try`, to obtain `run.id`) and the
    `session.flush()` inside the `except` block (to persist the failure) are
    themselves unguarded DB writes. If either raised — e.g. a dropped DB
    connection, or a DB-level error from `upsert_items` that left the session's
    transaction in an aborted state — the exception would propagate out of
    `collect_source`, technically breaking "never raises." I did not add
    recovery/rollback handling for this because (a) the brief's reference
    implementation has the identical gap, (b) it would require simulating a
    genuine driver/transaction failure to test meaningfully, which is out of this
    task's scope, and (c) the task explicitly warns against building beyond the
    brief's intent. Flagging it here rather than silently patching or silently
    ignoring it.
  - `should_attempt` has a defensive `if last_failure_at is None: return True`
    branch for a state that's logically unreachable given the invariant that
    `failures > 0` implies the most recent run was itself a failure. It's
    intentionally defensive against type (`Optional`) rather than a real code
    path, so I did not write a test that contrives that state (doing so would
    require manufacturing an inconsistent `fetch_runs` history).
- **No wall-clock reads:** `grep -n "datetime.now\|utcnow\|time.time"
  src/reachstore/collect.py` → no matches. Every time-dependent function takes
  `now: datetime` as a parameter.
- **No SQL / no query-building imports in `collect.py`:** `grep -n
  "sqlalchemy\|select(" src/reachstore/collect.py` → only `from sqlalchemy.orm
  import Session` (type hint only, discussed above); no `select`, `desc`,
  `insert`, or `func` usage.
- **Boundary correctness:** `should_attempt` uses `now >= last_failure_at +
  delay` (inclusive boundary — exactly enough elapsed time permits retry). Tested
  directly at the boundary in `test_should_attempt_at_exact_backoff_boundary`:
  one second before `NOW + BASE_BACKOFF` is blocked, exactly at `NOW +
  BASE_BACKOFF` is allowed.
- **`force` bypasses both mechanisms:** `collect_tier` only calls
  `should_attempt` when `force` is falsy (`if not force and not
  should_attempt(...)`), so with `force=True` neither the backoff wait nor the
  `FAILURE_LIMIT` cutoff is consulted at all. Covered by
  `test_force_overrides_the_circuit_breaker` (5 consecutive failures, still
  succeeds with `force=True`).
- **`consecutive_failures` ordering:** Orders by `started_at DESC` and stops at
  the first non-`"failed"` status, so a `fail, success, fail, fail` history (oldest
  to newest) correctly yields 2, not 3 or 4. Covered by
  `test_consecutive_failures_counts_only_the_recent_streak`.
- **Circular import:** Followed the brief's function-level import in
  `source_health` (`from reachstore.collect import FAILURE_LIMIT,
  consecutive_failures`), with the brief's explanatory comment kept. Additionally
  verified the new `collect.py -> query.py` module-level dependency does not
  create a cycle (see Deviation section above).
- **Tenant isolation:** `source_health` does not duplicate `visible_to` — it
  doesn't filter sources by tenant at all (sources aren't owned by a user; only
  items are), matching the brief's own design and the constraint "do not
  duplicate it in `source_health`."
- **Note on `MAX_BACKOFF` reachability:** With `FAILURE_LIMIT = 5`, the backoff
  calculation only ever runs for `failures` in `[1, 4]` (at `failures >= 5` the
  circuit breaker returns `False` unconditionally, before the backoff calc).
  `BASE_BACKOFF * 2**(4-1)` = 120 minutes, well under `MAX_BACKOFF` (24 hours), so
  `MAX_BACKOFF` can never actually engage under these exact constants. This is
  inherent to the brief's specified constants, not a bug — noting it for
  visibility only; the constant is still required for Task 8's interface and I
  left the `min(..., MAX_BACKOFF)` clamp in place as specified.
- **Test output:** full-suite run is pristine — no warnings, no skips.

## Issues, concerns, deviations — summary

1. **Deviation (flagged above):** relocated the brief's raw SQL out of
   `collect.py` into three new `query.py` functions, to satisfy the binding "no
   SQL in `collect.py`" global constraint that the brief's own Step 3 code
   contradicts. Behavior and public interfaces are unchanged; verified by the
   full test suite passing identically.
2. **Deviation (ruling 1 detail):** `error_text` includes the exception type name,
   not just `str(exc)`, per the ruling's explicit wording.
3. **Minor:** omitted the brief's unused `Item` import in `collect.py`.
4. **Known limitation, not fixed (see self-review):** `collect_source`'s two
   `session.flush()` calls outside the `try` are unguarded against DB-level
   failure; matches the brief's own reference design; out of scope to fix here.

No blockers. Status: DONE_WITH_CONCERNS only insofar as the SQL-location deviation
should be reviewed — everything else is a straightforward, fully-tested
implementation of the brief.

---

## Fix report: review round 2 (Critical — poisoned transaction escapes the bulkhead)

### What the review found

The reviewer traced the exact defect I had flagged myself as an unfixed known
gap in the original report: `upsert_items` (`store.py:46-64`) does per-item
`INSERT ... ON CONFLICT DO NOTHING`, which suppresses only the one named unique
constraint. A NOT NULL violation (or any other DB-level error) is not
suppressed — it aborts the enclosing Postgres transaction. When `collect_source`
caught that error and then tried `session.flush()` to record the failed
`fetch_run`, that flush ran against the already-aborted transaction and itself
raised, escaping `collect_source` uncaught. The bulkhead broke exactly when it
was needed: on a malformed item from a misbehaving adapter, the exact case
Ruling 1 exists to defend against.

### RED: confirming the defect was real before changing anything

Per instruction, I wrote the required test first and ran it against the
pre-fix code to confirm the failure mode, before touching `collect.py`.

Test added: `test_collect_tier_survives_a_poisoned_transaction_from_a_malformed_item`
in `tests/test_collect.py`. It builds a `NormalizedItem(external_id="1",
url=None, title="t", content_text="body")` — `url` is `NOT NULL` in the schema
(`models.py`: `url: Mapped[str] = mapped_column(Text)`), and `NormalizedItem` is
a plain frozen dataclass with no runtime validation, so `None` flows straight
through `upsert_items` into the `INSERT`. `url` was chosen specifically (over
`content_text`) because `content_text` is fed through `content_hash()` — i.e.
`text.encode("utf-8")` — before the INSERT is ever built, so a `None`
`content_text` would raise a plain `AttributeError` at the Python level and
never reach Postgres at all. `url` is passed straight into `.values(...)` with
no prior Python-side processing, so it reaches Postgres and triggers a genuine
`NotNullViolation`.

Command: `.venv/bin/pytest tests/test_collect.py::test_collect_tier_survives_a_poisoned_transaction_from_a_malformed_item -v`

Output (pre-fix, abbreviated to the load-bearing frames):

```
>       results = collect_tier(session, tier=1, registry=registry, raw_dir=raw_dir, now=NOW)

tests/test_collect.py:265:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
src/reachstore/collect.py:127: in collect_tier
    collect_source(session, source=source, adapter=adapter, raw_dir=raw_dir, now=now)
src/reachstore/collect.py:96: in collect_source
    session.flush()
...
self = <psycopg.Cursor [closed] [INTRANS] (host=localhost port=5433 user=reachstore database=reachstore_test) at 0x10d74c710>
query = 'UPDATE fetch_runs SET finished_at=%(finished_at)s::TIMESTAMP WITH TIME ZONE, status=%(status)s::VARCHAR, error_text=%(error_text)s::VARCHAR WHERE fetch_runs.id = %(fetch_runs_id)s::BIGINT'
...
E           sqlalchemy.exc.InternalError: (psycopg.errors.InFailedSqlTransaction) current transaction is aborted, commands ignored until end of transaction block
E           [SQL: UPDATE fetch_runs SET finished_at=%(finished_at)s::TIMESTAMP WITH TIME ZONE, status=%(status)s::VARCHAR, error_text=%(error_text)s::VARCHAR WHERE fetch_runs.id = %(fetch_runs_id)s::BIGINT]
E           [parameters: {'finished_at': ..., 'status': 'failed', 'error_text': 'IntegrityError: (psycopg.errors.NotNullViolation) null value in column "url" of relation "items" violates not-null constraint\nDETAIL:  Failing row c ... ', 'fetch_runs_id': 1}]

.venv/lib/python3.12/site-packages/psycopg/cursor.py:117: InternalError
=========================== short test summary info ============================
FAILED tests/test_collect.py::test_collect_tier_survives_a_poisoned_transaction_from_a_malformed_item - sqlalchemy.exc.InternalError: (psycopg.errors.InFailedSqlTransaction) current transaction is aborted, commands ignored until end of transaction block
============================== 1 failed in 0.44s ===============================
```

This confirms the finding's premise: the exception surfaced at
`collect.py:96` — exactly the recording flush inside the `except` block — as
`sqlalchemy.exc.InternalError` wrapping `psycopg.errors.InFailedSqlTransaction`
(the same defect the reviewer described; SQLAlchemy/psycopg surfaced it as
`InFailedSqlTransaction` in this exact code path rather than
`PendingRollbackError`, but it is the identical class of bug: an unguarded
write against an already-aborted transaction, escaping `collect_source`
uncaught). It escaped as a raw pytest error (an uncaught exception during the
test), not a clean assertion failure — consistent with `collect_source`
raising instead of returning.

### The fix

In `src/reachstore/collect.py`, `collect_source`:

1. Wrapped the fetch-and-store work (`adapter.fetch` + `upsert_items`) in
   `with session.begin_nested():` — a SAVEPOINT. On exception, SQLAlchemy rolls
   back to the savepoint and re-raises, leaving the outer transaction (and the
   already-flushed `run` row) usable.
2. Wrapped the failure-recording assignment + `session.flush()` in its own
   inner `try/except Exception: pass`, so that even if persisting the failed
   run still somehow fails, `collect_source` returns a `CollectResult` marked
   `"failed"` (with the original error's text) rather than raising. The
   original failure is never silently dropped — it's always in the returned
   `CollectResult`, even on the rare double-failure path where it can't also be
   persisted to `fetch_runs`.
3. The initial `run = FetchRun(...); session.add(run); session.flush()` stays
   unguarded, before the `try`/savepoint — per the reviewer's explicit
   instruction to keep it that way, since the `run` row must survive the
   savepoint rollback to be updated in the handler.
4. Rewrote the docstring to state the actual, narrower guarantee precisely:
   never raises for failures encountered while doing a source's work (adapter
   errors, DB-level rejections of malformed data); explicitly does not guard
   the initial "running"-row creation, which is an infrastructure precondition
   (DB reachable at all) rather than a per-source problem.

Also folded in the two minor findings, both in `src/reachstore/query.py`:

- `recent_fetch_statuses` and `last_run_started_at`: added `desc(FetchRun.id)`
  as a tie-breaker after `desc(FetchRun.started_at)` in both `ORDER BY`
  clauses, so two runs sharing an identical `started_at` have a deterministic
  relative order.
- `source_health`: added an inline comment above the function-local `from
  reachstore.collect import ...` explaining why it must stay local — a
  module-level import there would cycle, because `collect` now imports `query`
  (for `recent_fetch_statuses`, `last_run_started_at`, `sources_by_tier`).

The deferred third minor (consecutive_failures being capped at `FAILURE_LIMIT`
by construction) was left untouched, as instructed.

### GREEN: covering tests after the fix

Command: `.venv/bin/pytest tests/test_collect.py -v`

```
collected 13 items

tests/test_collect.py::test_successful_collection_stores_items_and_records_run PASSED
tests/test_collect.py::test_failing_adapter_records_failed_run_and_does_not_raise PASSED
tests/test_collect.py::test_one_failing_source_does_not_abort_the_run PASSED
tests/test_collect.py::test_collect_tier_only_touches_matching_tier PASSED
tests/test_collect.py::test_collect_tier_skips_kinds_with_no_adapter PASSED
tests/test_collect.py::test_consecutive_failures_counts_only_the_recent_streak PASSED
tests/test_collect.py::test_backoff_blocks_retry_immediately_after_failure PASSED
tests/test_collect.py::test_should_attempt_at_exact_backoff_boundary PASSED
tests/test_collect.py::test_circuit_breaker_opens_after_five_consecutive_failures PASSED
tests/test_collect.py::test_force_overrides_the_circuit_breaker PASSED
tests/test_collect.py::test_source_health_reports_attention_state PASSED
tests/test_collect.py::test_collect_tier_isolates_non_adapter_error_and_continues_with_next_source PASSED
tests/test_collect.py::test_collect_tier_survives_a_poisoned_transaction_from_a_malformed_item PASSED

============================== 13 passed in 0.23s ==============================
```

The new test now asserts (all satisfied): `collect_tier` returns normally with
two results in source-id order; the bad source's result and its persisted
`fetch_runs` row both show `status == "failed"` with a non-`None` `error_text`;
the good source's result and its `fetch_runs` row both show `status ==
"success"` — proving a subsequent source in the same `collect_tier` run
survives a poisoned transaction, not merely an ordinary caught exception.

### Full suite

Command: `.venv/bin/pytest`

```
============================== 60 passed in 0.31s ==============================
```

60 = the prior 59 (47 baseline + 10 brief + 2 from round 1) + 1 new test from
this round. `grep -i warning` over the full run's output: no matches.

### Files changed (this round)

- `src/reachstore/collect.py` — `collect_source` rewritten with savepoint +
  inner failure-recording guard; docstring rewritten
- `src/reachstore/query.py` — tie-breaker added to two `ORDER BY` clauses;
  comment added above the function-local import in `source_health`
- `tests/test_collect.py` — added
  `test_collect_tier_survives_a_poisoned_transaction_from_a_malformed_item`

Commit: `3c14dd2` — "fix: wrap collect_source's DB writes in a savepoint so a
poisoned transaction can't escape the bulkhead"

`store.py`, `models.py`, adapters, and the registry were not touched (verified
with `git status --short` / `git diff --stat` before committing — only the
three in-scope files appear).

### Residual note (not asked for, flagging for visibility only)

If persisting the failed run itself fails (the innermost `except Exception:
pass`), the session's transaction could in principle be left in a state that
also affects the *next* source `collect_tier` processes — a double-failure
scenario (savepoint fails to protect **and** the recording flush also fails).
This is not covered by a test: constructing it requires contriving two
independent DB failures in sequence, which is out of scope for what was asked
and risks adding untested recovery logic for a very unlikely case. Noting it
here rather than silently deciding it doesn't matter.
