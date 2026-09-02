# Task 1: Store-layer prerequisites — Report

## What I implemented

Exactly the brief's Steps 1–8, no more, no less.

1. **`src/reachstore/models.py`**
   - Imported `relationship` from `sqlalchemy.orm`.
   - Added `source: Mapped["Source"] = relationship(lazy="raise")` to `Item`, right after `content_hash`.

2. **`src/reachstore/query.py`**
   - Imported `selectinload` from `sqlalchemy.orm`.
   - `get_item`, `feed`, `search` each gained `.options(selectinload(Item.source))` on their `select(Item)` statement. No `where`/`order_by`/`limit`/`join` clauses touched.
   - `SourceStatus` gained `error_text: str | None` and `item_count: int`.
   - `source_health` now computes `counts` (one grouped query: `Item.source_id, func.count(Item.id)` grouped by `source_id`) before the per-source loop, and passes `error_text=last.error_text if last else None` and `item_count=counts.get(source.id, 0)` into each `SourceStatus`.

3. **Tests** (append-only, verbatim from the brief with one deliberate substitution):
   - `tests/test_query_isolation.py`: `test_feed_items_expose_their_source`, `test_get_item_exposes_its_source`, `test_search_items_expose_their_source`.
   - `tests/test_collect.py`: `test_source_health_reports_error_text_and_item_count`.

### Ambiguity resolved: search query term

`setup_two_users_with_private_items` seeds `content_text="alpha"` for all three items — never `"body"`. Per the brief's explicit instruction ("if `q="body"` returns nothing... pick a word that actually appears... do not weaken the assertion"), I used `q="alpha"` directly (the same term the pre-existing `test_search_excludes_other_users_private_items` already relies on), with a comment explaining why. I did not first prove `q="body"` fails empty-handed via a throwaway run — the content_text is unambiguous from reading the fixture, and starting with `"body"` would have produced a *different* RED failure (`assert results, "expected search hits"` failing before reaching `item.source`) than the one Step 2 specifies, so I went straight to the correct term.

## What I tested and the results

- Targeted RED run, then targeted GREEN run of the same four new tests plus the full `test_query_isolation.py` + `test_collect.py` (29 tests).
- Full suite: `.venv/bin/pytest -v` → **90 passed**, 1.49s–1.51s, no warnings, no skips.

## TDD Evidence

### RED

Command (brief's exact command — note pytest only honors the *last* `-k` flag when passed twice, so it only ran the `test_collect.py` test):
```
.venv/bin/pytest tests/test_query_isolation.py -k source tests/test_collect.py -k error_text -v
```
Output (relevant part):
```
tests/test_collect.py::test_source_health_reports_error_text_and_item_count FAILED

>       assert health[good.id].item_count == 1
               ^^^^^^^^^^^^^^^^^^^^^^^^^^
E       AttributeError: 'SourceStatus' object has no attribute 'item_count'

1 failed, 28 deselected in 0.50s
```

To also capture the `Item.source` failure (the other half of Step 2's expected output, which the combined `-k` invocation as literally written doesn't surface — the second `-k` overrides the first rather than combining), I additionally ran:
```
.venv/bin/pytest tests/test_query_isolation.py -k source -v
```
Output (relevant part):
```
tests/test_query_isolation.py::test_feed_items_expose_their_source FAILED
tests/test_query_isolation.py::test_get_item_exposes_its_source FAILED
tests/test_query_isolation.py::test_search_items_expose_their_source FAILED

>           assert item.source.identifier
                   ^^^^^^^^^^^
E           AttributeError: 'Item' object has no attribute 'source'

3 failed, 1 passed, 10 deselected in 0.19s
```
Both failures match the brief's Step 2 expectation exactly: `AttributeError: 'Item' object has no attribute 'source'` and `AttributeError: 'SourceStatus' object has no attribute 'item_count'`.

### GREEN

Command:
```
.venv/bin/pytest tests/test_query_isolation.py tests/test_collect.py -v
```
Output (tail):
```
tests/test_query_isolation.py::test_feed_items_expose_their_source PASSED
tests/test_query_isolation.py::test_get_item_exposes_its_source PASSED
tests/test_query_isolation.py::test_search_items_expose_their_source PASSED
...
tests/test_collect.py::test_source_health_reports_error_text_and_item_count PASSED
...
29 passed in 0.36s
```

Full suite:
```
.venv/bin/pytest -v
```
```
90 passed in 1.51s
```

## Files changed

- `/Users/dev2/Desktop/Testing/src/reachstore/models.py`
- `/Users/dev2/Desktop/Testing/src/reachstore/query.py`
- `/Users/dev2/Desktop/Testing/tests/test_query_isolation.py`
- `/Users/dev2/Desktop/Testing/tests/test_collect.py`

Commit: `7abc6ad feat: expose Item.source and add error_text/item_count to SourceStatus`

## Self-review findings

- **Completeness:** all 8 steps done; both interfaces from the brief (`Item.source`, `SourceStatus.error_text`/`item_count`) are present and eagerly loaded exactly where specified.
- **Quality:** names match the brief verbatim (`error_text`, `item_count`, `source`). No stray renames.
- **Discipline:** diff is a clean superset of the brief's snippets — `git diff` shows 4 files, 61 insertions / 5 deletions, nothing beyond what Steps 3–5 specify. No `lazy="select"` fallback needed; `lazy="raise"` never fired outside the new tests, so no existing call site needed a `selectinload` fix.
- **Testing:** the new tests assert real behavior (source identifier round-trips through `feed`/`get_item`/`search`; `item_count` reflects an actual stored item vs. zero for a failed collection; `error_text` carries the real adapter exception message) rather than restating the implementation. Output is pristine — no new warnings introduced.
- **No existing test or signature was modified** — confirmed via `git diff`, which shows only additions to the two test files and additive-only changes in the two source files.

## Concerns

None. This was a clean, mechanical application of the brief with one already-anticipated resolution (the search term).
