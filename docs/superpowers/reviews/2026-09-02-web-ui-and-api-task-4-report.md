# Task 4 Report: Per-source commits in `collect_tier`

## What I implemented

In `src/reachstore/collect.py`, `collect_tier`'s loop body now commits after
each `collect_source` call, wrapped so a commit failure cannot escape and
abort the rest of the tier:

```python
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

This is finding I4 from the Plan 1 review, previously deferred as
non-blocking for a CLI. It's needed now because a browser polling for
progress must see sources land one at a time, not a long pause followed by
everything at once. The diff is purely additive inside the existing loop —
no restructuring of `collect_tier` or `collect_source`.

Added `tests/test_collect_commits.py` verbatim from the brief, importing
`from test_collect import NOW, StubAdapter, add_source, one_item` (bare
module name — `tests/` has no `__init__.py` and no `pythonpath` config, so
the dotted `tests.test_collect` form is not importable under pytest's
rootdir-insertion).

## What I tested and the results

Full suite: `.venv/bin/pytest` → **107 passed** (104 pre-existing + 3 new),
0 failures, 0 warnings.

## TDD Evidence

**RED** — `.venv/bin/pytest tests/test_collect_commits.py -v`, run before
touching `collect.py`:

```
tests/test_collect_commits.py::test_each_source_is_committed_before_the_next_one_starts FAILED
tests/test_collect_commits.py::test_a_failing_commit_does_not_abort_the_rest_of_the_tier FAILED
tests/test_collect_commits.py::test_a_crash_mid_source_leaves_no_committed_running_row PASSED

2 failed, 1 passed in 0.21s
```

Test 1 failed with:
```
AssertionError: assert ['fetch:https://a/feed', 'fetch:https://b'] == ['fetch:https://a/feed', 'commit', 'fetch:https://b', 'commit']
```
— exactly the expected "fetches with no interleaved commits."

Test 2 failed with:
```
assert 0 == 3
```
This differs in *mechanism* from the brief's stated expectation ("the
second with `RuntimeError: connection lost` escaping `collect_tier`"), but
is the same root cause: today `collect_tier` never calls `session.commit()`
at all, so `flaky_commit` is never invoked and `attempts["n"]` stays 0 —
the `RuntimeError` branch is simply never reached pre-implementation. Once
the commit call exists, the second invocation of `flaky_commit` does raise,
and that's exactly what the wrapped commit in Step 3 has to swallow. I did
not alter the test to chase the brief's exact wording since the brief says
to use its tests verbatim and the failure is for the stated underlying
reason (no per-source commit exists yet).

Test 3 passed already, as the brief predicted: nothing is committed at all
today, so trivially no `running` row is committed either. It stays in the
suite as a regression guard once commits are added.

**GREEN** — `.venv/bin/pytest tests/test_collect_commits.py -v`, run after
the Step 3 change:

```
tests/test_collect_commits.py::test_each_source_is_committed_before_the_next_one_starts PASSED
tests/test_collect_commits.py::test_a_failing_commit_does_not_abort_the_rest_of_the_tier PASSED
tests/test_collect_commits.py::test_a_crash_mid_source_leaves_no_committed_running_row PASSED

3 passed in 0.19s
```

Full suite after the change: `.venv/bin/pytest` → `107 passed in 1.70s`, no
warnings.

## Step 5 finding: every return path in `collect_source` sets a terminal status first

Read `src/reachstore/collect.py` lines 56-140 in full. `collect_source` has
exactly two `return` statements after the initial `run = FetchRun(...,
status="running", ...)` at line 90-94:

- **Line 133** (`return CollectResult(source.id, "failed", 0, 0, error_text)`,
  inside the `except Exception as exc:` block starting at line 121): line 124
  sets `run.status = "failed"` unconditionally in memory before this return,
  regardless of whether the subsequent `session.flush()` at line 127
  succeeds — the inner `try/except Exception: pass` at lines 123-132 only
  guards the *persistence* of that failure, not the assignment, so the
  in-memory object is never left at `"running"` even if the flush itself
  fails.
- **Line 140** (`return CollectResult(source.id, "success", len(items),
  new_count, None)`): line 135 sets `run.status = "success"` before the
  `session.flush()` at line 139 and this return.

There is no third return path. The only way `collect_source` exits without
reaching one of these two statements is a `BaseException` (e.g.
`KeyboardInterrupt`) propagating out of the `try` block at line 96 — those
are not caught by the `except Exception` bulkhead at line 121 by design and
so never return at all; they propagate, which is exactly what Test 3
exercises and what the caller (`collect_tier`, and ultimately `collect`) is
responsible for not turning into a committed row. No path returns with
`run.status` still `"running"`.

## Files changed

- `src/reachstore/collect.py` — `collect_tier` loop body: commit each
  source's result, wrapped in try/except with rollback on failure.
- `tests/test_collect_commits.py` — new, 3 tests, verbatim from the brief.

## Self-review findings

- Diff is exactly the loop-body addition specified in Step 3, nothing else
  touched in `collect.py`. `collect_source` untouched.
- Comment on the guard states the actual reason (bulkhead must extend to
  the commit, or a dropped connection/deadlock aborts the whole tier) —
  not just "catches exceptions."
- No SQL, no restructuring, no new abstractions — a `try/except` inside an
  existing loop.
- Verified via the Step 5 reading (not just trusting Test 3) that no
  `collect_source` return path can leave `run.status == "running"`.
- Confirmed test 2's committed-then-rolled-back ordering matches the
  brief's stated mechanism: attempt 1 (rss) commits for real and persists
  the sources' fetch_run rows created earlier in the same commit; attempt 2
  (web_page) raises and is rolled back, but by then the `sources` rows
  (added via `add_source` before `collect_tier` even runs, and flushed
  independently) already exist, so attempt 3 (github_repo) has no
  foreign-key problem and still runs and returns a result — hence
  `len(results) == 3` while `attempts["n"] == 3` too (the third call
  succeeds since `attempts["n"]` only equals 2 on the second call).
- No new warnings; full suite 107/107 green.

## Concerns

None. One minor note already covered above: the brief's predicted RED
failure text for test 2 (`RuntimeError: connection lost escaping
collect_tier`) doesn't literally match what I observed pre-implementation
(`assert 0 == 3`, since no commit call exists yet to raise from) — but the
underlying reason (no per-source commit) is identical, and I left the test
verbatim per instructions rather than "fixing" it.

---

# Fix report: review findings on Task 4 (2026-09-02)

Review of the initial commit (`48d3f71`) came back with three findings and
one clarity request. All addressed in commit `54ee1b8`.

## Finding 1 (Important) — swallowed commit failure reported success for discarded work

**Problem:** `collect_source`'s `CollectResult` was appended to `results`
*before* `session.commit()` ran. When commit raised and the handler rolled
back, the already-appended result still read `status="success"` with the
item counts from the now-discarded work. `cli.py` acts on that result
directly (`typer.echo(f"source {n}: {new} new / {found} found")` at
line ~93, and the all-failed exit path `if results and all(r.status ==
"failed" for r in results): raise typer.Exit(code=1)` at lines 98-99) — so a
systemic commit failure across every source would print full success lines
and exit 0 with nothing persisted, and do it silently since there is no
logging anywhere in `src/reachstore`.

**Fix** — `src/reachstore/collect.py`, in the `except` branch after
`session.rollback()`:

```python
            results[-1] = replace(
                results[-1],
                status="failed",
                items_found=0,
                items_new=0,
                error_text=f"commit failed: {type(exc).__name__}: {exc}",
            )
```

with `replace` added to the existing `from dataclasses import dataclass`
import (`from dataclasses import dataclass, replace`), and `except
Exception:` changed to `except Exception as exc:` to capture the error.

**Covering test** — `tests/test_collect_commits.py::
test_a_failing_commit_produces_a_failed_result_not_a_stale_success`: forces
every `session.commit()` call to raise, then asserts the single
`CollectResult` returned has `status == "failed"`, `items_found == 0`,
`items_new == 0`, and an `error_text` mentioning "commit". Fails against the
pre-fix code (`status == "success"`).

## Finding 2 (Important, plan-mandated) — handler comment described a recovery that cannot happen

**Problem:** the original comment claimed "if the database is genuinely
gone, every remaining source records a failure and `collect` exits 1
through the existing all-sources-failed path." False: `session.rollback()`
unconditionally expires the ORM identity map (`expire_on_commit=False` does
not suppress this), so on the next loop iteration, reading any attribute off
the next `Source` (`source.kind` for the registry lookup, `source.id` inside
`should_attempt`) triggers an implicit refresh query. Both of those call
sites sit outside the `try` and outside `collect_source`'s bulkhead, so with
the database actually gone, the refresh raises and the exception is
unhandled — the tier aborts with a traceback, not a clean per-source
failure list.

**Fix (comment only, per the reviewer's ruling — no behavior change):**

```python
            # is usable again. This only covers a commit failure the database
            # itself survives: rollback() expires the identity map, so on the
            # next loop iteration merely reading an attribute (e.g.
            # source.kind, source.id) off the next Source triggers a refresh
            # query outside this try and outside collect_source's bulkhead --
            # if the database is actually gone, that query raises and aborts
            # the tier.
```

No test added for this — it's a comment correction, and the reviewer's
ruling was explicitly not to restructure the loop to guard those call sites.

## Finding 3 (Minor, ruled into scope) — rollback itself was untested

**Problem:** in `test_a_failing_commit_does_not_abort_the_rest_of_the_tier`,
`flaky_commit` raises before ever calling `real_commit()`, so the session's
transaction is never touched by that test and remains active regardless of
whether the handler calls `session.rollback()`. Replacing
`session.rollback()` with `pass` in `collect.py` left that test green.

**Covering test** —
`tests/test_collect_commits.py::test_a_failing_commit_rolls_back_the_session`:
wraps `session.rollback` in a spy, uses the same `flaky_commit` pattern as
the existing test (first commit succeeds for real so the flushed `sources`
rows survive, second commit raises), and asserts `events == ["rollback"]`.

**Evidence the test catches a missing rollback** — I temporarily edited
`src/reachstore/collect.py`, replacing the `session.rollback()` call in the
except branch with `pass`, then ran:

```
.venv/bin/pytest tests/test_collect_commits.py::test_a_failing_commit_rolls_back_the_session -v
```

Output:

```
>       assert events == ["rollback"]
E       AssertionError: assert [] == ['rollback']
E
E         Right contains one more item: 'rollback'
E
E         Full diff:
E         + []
E         - [
E         -     'rollback',
E         - ]

tests/test_collect_commits.py:155: AssertionError
FAILED tests/test_collect_commits.py::test_a_failing_commit_rolls_back_the_session - AssertionError: assert [] == ['rollback']
1 failed in 0.15s
```

I then restored the real `collect.py` from a backup taken before the edit
(`diff` confirmed the restore was byte-for-byte identical) and re-ran the
full suite to confirm it was clean again.

## Clarity fix — `test_a_crash_mid_source_leaves_no_committed_running_row` docstring

Added a paragraph clarifying that this test already passed before per-source
commits existed (nothing was committed at all pre-change), and that it now
serves as a regression guard against a future refactor — e.g. moving the
commit into a `finally`, or widening the bulkhead to `except BaseException`
— that would start committing a row still at `"running"`. No behavior or
assertion change.

## Re-run results

`.venv/bin/pytest tests/test_collect_commits.py tests/test_collect.py -v`:

```
tests/test_collect_commits.py::test_each_source_is_committed_before_the_next_one_starts PASSED
tests/test_collect_commits.py::test_a_failing_commit_does_not_abort_the_rest_of_the_tier PASSED
tests/test_collect_commits.py::test_a_failing_commit_produces_a_failed_result_not_a_stale_success PASSED
tests/test_collect_commits.py::test_a_failing_commit_rolls_back_the_session PASSED
tests/test_collect_commits.py::test_a_crash_mid_source_leaves_no_committed_running_row PASSED
tests/test_collect.py:: (15 tests) ... all PASSED

20 passed in 0.23s
```

`.venv/bin/pytest` (full suite):

```
109 passed in 1.67s
```

(was 107 before this round; +2 new tests, 0 failures, 0 warnings — grepped
explicitly for "warning" in the full-suite output, no matches outside test
names).

## Files changed (this round)

- `src/reachstore/collect.py` — capture the commit exception, replace the
  discarded-work `CollectResult` with a failed one after rollback, correct
  the handler comment.
- `tests/test_collect_commits.py` — two new tests (Findings 1 and 3), one
  docstring addition (clarity fix).

## Commit

`54ee1b8` — "fix: replace discarded-work result on commit failure and cover
rollback (I4 review)"

## Concerns

None. Finding 2 is a comment-only fix per the reviewer's explicit ruling not
to restructure `collect_tier` to guard the post-rollback attribute-access
call sites — that remains a known, accepted gap (traceback instead of a
clean per-source failure, if the database is truly gone), not something this
round changed behaviorally.
