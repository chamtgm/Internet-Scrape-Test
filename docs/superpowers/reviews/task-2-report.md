# Task 2 Report: Store layer with idempotent upserts

## What I implemented

Following the brief in `task-2-brief.md` exactly, step by step:

1. **`src/reachstore/adapters/__init__.py`** — empty package init file.
2. **`src/reachstore/adapters/base.py`** — `NormalizedItem`, a frozen dataclass with fields
   `external_id`, `url`, `content_text`, `title`, `author_handle`, `published_at`, `raw`.
   This is the shared type that Task 4 will append protocols below (file left minimal,
   nothing added beyond the brief's exact code block).
3. **`tests/test_store.py`** — all 5 tests copied verbatim from the brief:
   `test_upsert_inserts_new_items`, `test_upsert_is_idempotent`,
   `test_upsert_writes_raw_payload_to_disk`, `test_upsert_records_owner_for_private_items`,
   `test_same_external_id_different_sources_are_distinct`.
4. **`src/reachstore/store.py`** — implemented exactly per the brief:
   - `content_hash(text: str) -> str` — SHA-256 hex digest of the UTF-8 encoded text.
   - `_write_raw(raw_dir, source_id, digest, raw) -> str` — private helper, writes the raw
     payload JSON to `{raw_dir}/{source_id}/{digest}.json`, returns the path relative to
     `raw_dir`.
   - `upsert_items(session, *, source_id, items, owner_user_id, raw_dir, now) -> int` —
     loops over items, computes `content_hash`, writes raw payload to disk (only when
     `item.raw` is truthy), and does a Postgres `INSERT ... ON CONFLICT (uq_items_source_external)
     DO NOTHING RETURNING id` per item. Counts a row as newly inserted only when the
     `RETURNING` clause yields a row (i.e., the conflict target did NOT fire). Calls
     `session.flush()` once at the end. Never reads the wall clock — `now` is the only time
     source, written straight to `fetched_at`. `content_tsv` is never referenced (DB-computed
     column).

The idempotency guarantee rests entirely on the database's unique constraint
(`uq_items_source_external`) via `on_conflict_do_nothing`, not on any pre-check in Python —
per the task's explicit instruction not to substitute a SELECT-then-insert strategy.

## TDD Evidence

### RED

Command: `.venv/bin/pytest tests/test_store.py -v`

Run after creating `adapters/__init__.py`, `adapters/base.py`, and `tests/test_store.py`,
but **before** creating `src/reachstore/store.py`.

```
============================= test session starts ==============================
platform darwin -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- /Users/dev2/Desktop/Testing/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/dev2/Desktop/Testing
configfile: pyproject.toml
plugins: cov-7.1.0, anyio-4.14.2
collecting ... collected 0 items / 1 error

==================================== ERRORS ====================================
_____________________ ERROR collecting tests/test_store.py _____________________
ImportError while importing test module '/Users/dev2/Desktop/Testing/tests/test_store.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
.venv/lib/python3.12/site-packages/_pytest/python.py:508: in importtestmodule
    mod = import_path(
.venv/lib/python3.12/site-packages/_pytest/pathlib.py:596: in import_path
    importlib.import_module(module_name)
../../.local/share/uv/python/cpython-3.12.13-macos-aarch64-none/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
<frozen importlib._bootstrap>:1387: in _gcd_import
    ???
<frozen importlib._bootstrap>:1360: in _find_and_load
    ???
<frozen importlib._bootstrap>:1331: in _find_and_load_unlocked
    ???
<frozen importlib._bootstrap>:935: in _load_unlocked
    ???
.venv/lib/python3.12/site-packages/_pytest/assertion/rewrite.py:188: in exec_module
    exec(co, module.__dict__)
tests/test_store.py:8: in <module>
    from reachstore.store import upsert_items
E   ModuleNotFoundError: No module named 'reachstore.store'
=========================== short test summary info ============================
ERROR tests/test_store.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
=============================== 1 error in 0.07s ===============================
```

This is exactly the expected failure: `ModuleNotFoundError: No module named 'reachstore.store'`,
because `src/reachstore/store.py` did not yet exist. No other errors (e.g. syntax errors in the
test file, missing fixtures) were present — confirming the test file itself was well-formed and
only the missing module blocked collection.

### GREEN

Command: `.venv/bin/pytest tests/test_store.py -v`

Run after creating `src/reachstore/store.py`.

```
============================= test session starts ==============================
platform darwin -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- /Users/dev2/Desktop/Testing/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/dev2/Desktop/Testing
configfile: pyproject.toml
plugins: cov-7.1.0, anyio-4.14.2
collecting ... collected 5 items

tests/test_store.py::test_upsert_inserts_new_items PASSED                [ 20%]
tests/test_store.py::test_upsert_is_idempotent PASSED                    [ 40%]
tests/test_store.py::test_upsert_writes_raw_payload_to_disk PASSED       [ 60%]
tests/test_store.py::test_upsert_records_owner_for_private_items PASSED  [ 80%]
tests/test_store.py::test_same_external_id_different_sources_are_distinct PASSED [100%]

============================== 5 passed in 0.16s ===============================
```

All 5 pass. Output is pristine — no warnings, no deprecation notices.

## Full-suite result before committing

Command: `.venv/bin/pytest -v`

```
============================= test session starts ==============================
platform darwin -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- /Users/dev2/Desktop/Testing/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/dev2/Desktop/Testing
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, anyio-4.14.2
collecting ... collected 8 items

tests/test_schema.py::test_all_tables_exist PASSED                       [ 12%]
tests/test_schema.py::test_items_has_generated_tsvector_column PASSED    [ 25%]
tests/test_schema.py::test_tsvector_index_exists PASSED                  [ 37%]
tests/test_store.py::test_upsert_inserts_new_items PASSED                [ 50%]
tests/test_store.py::test_upsert_is_idempotent PASSED                    [ 62%]
tests/test_store.py::test_upsert_writes_raw_payload_to_disk PASSED       [ 75%]
tests/test_store.py::test_upsert_records_owner_for_private_items PASSED  [ 87%]
tests/test_store.py::test_same_external_id_different_sources_are_distinct PASSED [100%]

============================== 8 passed in 0.12s ===============================
```

8/8 passing, including Task 1's `test_schema.py` tests — no regressions.

## Files changed (committed)

- `src/reachstore/adapters/__init__.py` (new, empty)
- `src/reachstore/adapters/base.py` (new — `NormalizedItem`)
- `src/reachstore/store.py` (new — `content_hash`, `_write_raw`, `upsert_items`)
- `tests/test_store.py` (new — 5 tests, verbatim from brief)

Commit: `e4fb563` — "feat: idempotent item store with raw payload persistence"

## Self-review findings

- **Completeness:** all steps from the brief implemented; both public functions
  (`upsert_items`, `content_hash`) match the required signatures exactly, including the
  keyword-only arguments in `upsert_items`.
- **Quality:** code matches the brief's implementation verbatim, since the brief specified
  the exact implementation to use (this is a spec-driven task, not an open design). Names
  are accurate: `_write_raw` is private (not part of the public interface later tasks
  depend on), `content_hash` and `upsert_items` are the two public symbols.
- **Discipline (YAGNI):** did not add anything beyond the brief — no extra helpers, no
  logging, no extra validation. `adapters/base.py` contains only `NormalizedItem`, left
  open for Task 4 to append protocols below it.
- **Testing:** all 5 tests exercise the real Postgres 16 database via the `session` fixture
  (no mocks) — including the actual `ON CONFLICT ... DO NOTHING` behavior enforced by the
  `uq_items_source_external` constraint, and real filesystem writes to `raw_dir` (via
  pytest's `tmp_path`). Output is clean: no warnings, no deprecation notices, no stray
  print statements.

## Deviations from the brief

None. Implementation, test file, and commit message match the brief verbatim. The only
judgment call was **not** to `git add -A` as the brief's Step 6 literally shows — the
working tree had a pre-existing uncommitted modification to
`docs/superpowers/plans/2026-08-13-core-store-and-tier1-collection.md` left over from
Task 1's review process (an amendment note about index metadata, unrelated to Task 2). I
staged only the four Task 2 files by name instead, per the repo's git safety protocol
(prefer explicit file staging over `git add -A`/`.`). That doc change remains unstaged and
untouched.

---

## Fix report — raw payload filename collision (post-review)

The review of `e4fb563` found an Important-severity defect (governing over the brief, per
the human's ruling): `_write_raw` named the raw JSON file after `content_hash(item.content_text)`.
Two distinct items from the same source with identical `content_text` but different
`external_id` hashed to the same filename, so the second item's raw write silently
overwrote the first's — while `Item.raw_path` for the first row kept pointing at a file that
now held the second item's payload. Separately, the raw write happened unconditionally
*before* the insert was attempted, so a conflict-skipped row (existing item, changed
content on replay) still produced an orphan file on disk.

### What I changed

`src/reachstore/store.py`:

- `_write_raw` signature changed from `_write_raw(raw_dir: Path, source_id: int, digest: str, raw: dict) -> str`
  to `_write_raw(raw_dir: Path, relative: Path, raw: dict[str, Any]) -> None`. It no longer
  computes the path — it just writes to `raw_dir / relative` — and no longer returns
  anything, since the caller already knows the path it decided on. `raw` is now typed
  `dict[str, Any]` to match `NormalizedItem.raw` (the Minor finding folded into this fix).
- `upsert_items` now computes `relative = Path(str(source_id)) / f"{content_hash(item.external_id)}.json"`
  before building the INSERT statement (the identity-derived filename), and passes
  `raw_path=str(relative) if item.raw else None` into `.values(...)` — unchanged from
  before in spirit, just a different digest source. `content_hash(item.content_text)` is
  still computed and still stored in the `content_hash` column — only the *filename* changed
  its input.
- The raw file write itself (`_write_raw(raw_dir, relative, item.raw)`) moved to *after*
  `session.execute(stmt).scalar_one_or_none() is not None` succeeds — i.e., only on rows the
  database actually inserted. A conflict-skipped row now performs zero filesystem writes.
- No change to the idempotency mechanism (`on_conflict_do_nothing(constraint="uq_items_source_external")`),
  the returned count semantics, or `now`/wall-clock handling.

This matches the target shape given in the review finding exactly.

`tests/test_store.py` — two new tests appended after `test_same_external_id_different_sources_are_distinct`:

- `test_upsert_writes_distinct_raw_files_for_identical_content` — two `NormalizedItem`s on
  the same source, same `content_text` ("same content"), different `external_id`
  ("dup-1"/"dup-2") and different `raw` payloads. Asserts both rows inserted (`new_count == 2`),
  their `raw_path` values differ, and each row's own file on disk round-trips its own `raw`
  payload (not the other's).
- `test_upsert_does_not_rewrite_raw_file_on_replay` — upserts one item, then overwrites its
  raw file on disk with a sentinel (`{"sentinel": True}`), then calls `upsert_items` again
  with the same item. Asserts the second call returns `0` and the file still contains the
  sentinel — proving the conflict-skipped replay performed no filesystem write.

### Why regression test 1 would have failed against the old code (verified empirically)

I did not just reason about this — I checked it out and ran it. I copied the pre-fix
`store.py` from commit `e4fb563` (`git show e4fb563:src/reachstore/store.py`) back into
`src/reachstore/store.py`, ran only the new test against it, then restored the fixed file.

Command: `.venv/bin/pytest tests/test_store.py::test_upsert_writes_distinct_raw_files_for_identical_content -v`
(run with the OLD `store.py` in place)

```
tests/test_store.py::test_upsert_writes_distinct_raw_files_for_identical_content FAILED [100%]

=================================== FAILURES ===================================
_________ test_upsert_writes_distinct_raw_files_for_identical_content __________
...
    rows = {row.external_id: row for row in session.execute(select(Item)).scalars().all()}
>   assert rows["dup-1"].raw_path != rows["dup-2"].raw_path
E   AssertionError: assert '1/a636bd7cd42060a4d07fa1bfbcc010eb7794c2ba721e1e3e4c20335a15b66eaf.json' != '1/a636bd7cd42060a4d07fa1bfbcc010eb7794c2ba721e1e3e4c20335a15b66eaf.json'
E    +  where '1/a636bd7cd42060a4d07fa1bfbcc010eb7794c2ba721e1e3e4c20335a15b66eaf.json' = <reachstore.models.Item object at 0x109abfdd0>.raw_path
E    +  and   '1/a636bd7cd42060a4d07fa1bfbcc010eb7794c2ba721e1e3e4c20335a15b66eaf.json' = <reachstore.models.Item object at 0x109abfd70>.raw_path

tests/test_store.py:118: AssertionError
=========================== short test summary info ============================
FAILED tests/test_store.py::test_upsert_writes_distinct_raw_files_for_identical_content
============================== 1 failed in 0.16s ===============================
```

This confirms the exact defect: both rows got the identical filename
(`1/a636bd7cd42...json`, the SHA-256 of `"same content"`), because the old code hashed
`content_text` instead of `external_id` for the filename. The second write in the loop
silently clobbered the first item's raw archive on disk, and the two DB rows' `raw_path`
columns are indistinguishable — exactly the "no error, no signal" corruption the review
flagged. The file was restored to the fixed version immediately after (`diff` confirmed
byte-identical restoration) before running any further tests.

### GREEN — after the fix

Command: `.venv/bin/pytest tests/test_store.py -v`

```
============================= test session starts ==============================
platform darwin -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- /Users/dev2/Desktop/Testing/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/dev2/Desktop/Testing
configfile: pyproject.toml
plugins: cov-7.1.0, anyio-4.14.2
collecting ... collected 7 items

tests/test_store.py::test_upsert_inserts_new_items PASSED                [ 14%]
tests/test_store.py::test_upsert_is_idempotent PASSED                    [ 28%]
tests/test_store.py::test_upsert_writes_raw_payload_to_disk PASSED       [ 42%]
tests/test_store.py::test_upsert_records_owner_for_private_items PASSED  [ 57%]
tests/test_store.py::test_same_external_id_different_sources_are_distinct PASSED [ 71%]
tests/test_store.py::test_upsert_writes_distinct_raw_files_for_identical_content PASSED [ 85%]
tests/test_store.py::test_upsert_does_not_rewrite_raw_file_on_replay PASSED [100%]

============================== 7 passed in 0.13s ===============================
```

7/7 passing (the original 5 unmodified, plus the 2 new regression tests). Output pristine —
no warnings, no deprecation notices.

### Full suite — after the fix

Command: `.venv/bin/pytest -v`

```
============================= test session starts ==============================
platform darwin -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- /Users/dev2/Desktop/Testing/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/dev2/Desktop/Testing
configfile: pyproject.toml
testpaths: tests
plugins: cov-7.1.0, anyio-4.14.2
collecting ... collected 10 items

tests/test_schema.py::test_all_tables_exist PASSED                       [ 10%]
tests/test_schema.py::test_items_has_generated_tsvector_column PASSED    [ 20%]
tests/test_schema.py::test_tsvector_index_exists PASSED                  [ 30%]
tests/test_store.py::test_upsert_inserts_new_items PASSED                [ 40%]
tests/test_store.py::test_upsert_is_idempotent PASSED                    [ 50%]
tests/test_store.py::test_upsert_writes_raw_payload_to_disk PASSED       [ 60%]
tests/test_store.py::test_upsert_records_owner_for_private_items PASSED  [ 70%]
tests/test_store.py::test_same_external_id_different_sources_are_distinct PASSED [ 80%]
tests/test_store.py::test_upsert_writes_distinct_raw_files_for_identical_content PASSED [ 90%]
tests/test_store.py::test_upsert_does_not_rewrite_raw_file_on_replay PASSED [100%]

============================== 10 passed in 0.14s ==============================
```

10/10 passing — no regressions in Task 1's `test_schema.py` tests, no regressions in the
original 5 `test_store.py` tests.

### Files changed (this fix)

- `src/reachstore/store.py` (modified — `_write_raw` signature and call site, filename now
  derived from `external_id`, write moved to after successful insert)
- `tests/test_store.py` (modified — 2 new regression tests appended)

Commit: `c5b097c` — "fix: name raw payload files by item identity, not content hash"

### Notes

- `Item.content_hash` still stores `content_hash(item.content_text)`, unchanged — only the
  raw file's *name* now derives from `content_hash(item.external_id)`, per the review's
  explicit instruction not to conflate the two.
- The idempotency mechanism, the returned insertion count, and wall-clock handling
  (`now` parameter) are all untouched, as required.
- No other findings from the review remained open — the Minor `dict[str, Any]` typing note
  was folded into the `_write_raw` signature change above.
