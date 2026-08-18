# Task 3 Report: Query layer with tenant isolation

## What I implemented

- `tests/test_query_isolation.py` — 4 tests, written verbatim from the brief (Step 1).
- `tests/test_query_search.py` — 5 tests, written verbatim from the brief (Step 2).
- `src/reachstore/query.py` — the read path, with four functions:
  - `visible_to(user_id: int) -> ColumnElement[bool]` — the **sole** place the tenant-isolation
    predicate (`owner_user_id IS NULL OR owner_user_id == user_id`) is expressed. Verified by
    grep: `owner_user_id` appears in `query.py` only inside `visible_to`'s docstring and body —
    nowhere else in the file.
  - `get_item(session, *, user_id, item_id) -> Item | None` — calls `visible_to(user_id)`.
  - `feed(session, *, user_id, limit=50, before_id=None) -> list[Item]` — calls
    `visible_to(user_id)`, supports keyset pagination via `before_id`.
  - `search(session, *, user_id, q, kinds=None, since=None, subscribed_only=False, limit=50) -> list[Item]`
    — calls `visible_to(user_id)`, uses `websearch_to_tsquery` against `Item.content_tsv`,
    ranks with `ts_rank`, optionally joins `Source` (for `kinds`) and/or `Subscription` (for
    `subscribed_only`). Both joins can be present simultaneously without introducing duplicate
    rows, because `Subscription` has a `(user_id, source_id)` unique constraint, so each item
    joins to at most one subscription row for the given user regardless of whether `Source` is
    also joined.

The implementation follows the brief's Step 4 code exactly, with one bug fix (see Deviations
below).

## TDD Evidence

### RED

Command: `.venv/bin/pytest tests/test_query_isolation.py tests/test_query_search.py -v`

Output (relevant excerpt, before `query.py` existed):

```
collecting ... collected 0 items / 2 errors

==================================== ERRORS ====================================
________________ ERROR collecting tests/test_query_isolation.py ________________
...
tests/test_query_isolation.py:5: in <module>
    from reachstore.query import feed, get_item, search
E   ModuleNotFoundError: No module named 'reachstore.query'
_________________ ERROR collecting tests/test_query_search.py __________________
...
tests/test_query_search.py:5: in <module>
    from reachstore.query import search
E   ModuleNotFoundError: No module named 'reachstore.query'
=========================== short test summary info ============================
ERROR tests/test_query_isolation.py
ERROR tests/test_query_search.py
!!!!!!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!!!!!!!
============================== 2 errors in 0.08s ===============================
```

This is exactly the expected failure per the brief's Step 3: `reachstore.query` did not exist
yet, so both test modules failed at import/collection time with `ModuleNotFoundError`. No test
bodies ran, confirming the tests are wired to the not-yet-built module and not accidentally
passing for the wrong reason.

### GREEN

Command: `.venv/bin/pytest tests/test_query_isolation.py tests/test_query_search.py -v`

Output (after implementing `query.py`, after fixing the `feed` ordering bug — see Deviations):

```
collecting ... collected 9 items

tests/test_query_isolation.py::test_feed_excludes_other_users_private_items PASSED [ 11%]
tests/test_query_isolation.py::test_search_excludes_other_users_private_items PASSED [ 22%]
tests/test_query_isolation.py::test_get_item_refuses_other_users_private_item PASSED [ 33%]
tests/test_query_isolation.py::test_subscribed_only_limits_to_subscribed_sources PASSED [ 44%]
tests/test_query_search.py::test_search_matches_content_and_title PASSED [ 55%]
tests/test_query_search.py::test_search_ignores_non_matching_documents PASSED [ 66%]
tests/test_query_search.py::test_search_filters_by_kind PASSED           [ 77%]
tests/test_query_search.py::test_search_filters_by_since PASSED          [ 88%]
tests/test_query_search.py::test_search_ranks_title_matches_above_body_matches PASSED [100%]

============================== 9 passed in 0.16s ===============================
```

9/9 passing, including `test_search_ranks_title_matches_above_body_matches` (verifies the
`setweight('A')` title-vs-body ranking) and `test_subscribed_only_limits_to_subscribed_sources`
(verifies the `Subscription` join). Output is pristine — no warnings.

## Full-suite result before committing

Command: `.venv/bin/pytest`

```
collecting ... collected 19 items

tests/test_query_isolation.py::test_feed_excludes_other_users_private_items PASSED [  5%]
tests/test_query_isolation.py::test_search_excludes_other_users_private_items PASSED [ 10%]
tests/test_query_isolation.py::test_get_item_refuses_other_users_private_item PASSED [ 15%]
tests/test_query_isolation.py::test_subscribed_only_limits_to_subscribed_sources PASSED [ 21%]
tests/test_query_search.py::test_search_matches_content_and_title PASSED [ 26%]
tests/test_query_search.py::test_search_ignores_non_matching_documents PASSED [ 31%]
tests/test_query_search.py::test_search_filters_by_kind PASSED           [ 36%]
tests/test_query_search.py::test_search_filters_by_since PASSED          [ 42%]
tests/test_query_search.py::test_search_ranks_title_matches_above_body_matches PASSED [ 47%]
tests/test_schema.py::test_all_tables_exist PASSED                       [ 52%]
tests/test_schema.py::test_items_has_generated_tsvector_column PASSED    [ 57%]
tests/test_schema.py::test_tsvector_index_exists PASSED                  [ 63%]
tests/test_store.py::test_upsert_inserts_new_items PASSED                [ 68%]
tests/test_store.py::test_upsert_is_idempotent PASSED                    [ 73%]
tests/test_store.py::test_upsert_writes_raw_payload_to_disk PASSED       [ 78%]
tests/test_store.py::test_upsert_records_owner_for_private_items PASSED  [ 84%]
tests/test_store.py::test_same_external_id_different_sources_are_distinct PASSED [ 89%]
tests/test_store.py::test_upsert_writes_distinct_raw_files_for_identical_content PASSED [ 94%]
tests/test_store.py::test_upsert_does_not_rewrite_raw_file_on_replay PASSED [100%]

============================== 19 passed in 0.19s ==============================
```

19/19 passing (Tasks 1, 2, and 3 all green together), pristine output.

## Files changed

- Created: `/Users/dev2/Desktop/Testing/src/reachstore/query.py`
- Created: `/Users/dev2/Desktop/Testing/tests/test_query_isolation.py`
- Created: `/Users/dev2/Desktop/Testing/tests/test_query_search.py`

Committed in `8aa462a` — "feat: query layer with tenant isolation and full-text search".

Note: `docs/superpowers/plans/2026-08-13-core-store-and-tier1-collection.md` had a pre-existing
unstaged modification from Task 2's amendment note (unrelated to this task). I left it untouched
and staged/committed only my three Task 3 files.

## Self-review findings

- **Completeness:** all four functions (`visible_to`, `get_item`, `feed`, `search`) implemented
  with the exact signatures from the brief and Task interfaces list. Nothing missing.
- **Security:** confirmed by grep that `owner_user_id` is referenced in `query.py` only inside
  `visible_to`. All three read functions (`get_item`, `feed`, `search`) call `visible_to(user_id)`
  — none re-expresses or inlines the ownership condition. No parameter combination (kinds,
  since, subscribed_only, before_id, limit) bypasses `visible_to`, since it's unconditionally
  included in every `.where()` clause.
  - Also verified the `subscribed_only` + `kinds` combination together cannot produce duplicate
    rows: `Subscription` carries a `uq_subscriptions_user_source` unique constraint on
    `(user_id, source_id)`, so joining both `Source` and `Subscription` for a fixed `user_id`
    still yields at most one matching row per item.
  - Confirmed no other module in `src/reachstore/` imports `sqlalchemy.select` — only
    `query.py` and `store.py` contain SQL, per the global constraint.
- **Quality:** names match the brief precisely. Docstring on `visible_to` states its role as the
  sole security boundary, which matches the constraint in the task instructions.
- **Discipline (YAGNI):** implemented only the four functions the brief specifies — no
  pagination helpers, no extra filters, no convenience wrappers, nothing beyond the brief.
- **Testing:** all 9 new tests run against the real Postgres 16 test database (via the `session`
  fixture, transactional rollback) — no mocks. `test_search_ranks_title_matches_above_body_matches`
  passed without weakening the assertion or reordering fixture data, confirming the real
  `setweight('A')`/`setweight('B')` ranking behavior works as designed. Output is clean with no
  stray warnings across both the focused run and the full 19-test suite.

## Issues, concerns, or deviations from the brief

One deviation, a bug fix:

- The brief's Step 4 code for `feed` used:
  ```python
  stmt = stmt.order_by(desc(Item.published_at.nulls_last()), desc(Item.id)).limit(limit)
  ```
  Running this against real PostgreSQL 16 raised `psycopg.errors.SyntaxError: syntax error at or
  near "DESC"` — SQLAlchemy compiled `Item.published_at.nulls_last()` wrapped in `desc(...)` to
  the SQL fragment `published_at NULLS LAST DESC`, which is invalid order-by syntax (Postgres
  requires `DESC NULLS LAST`, not `NULLS LAST DESC`). This is a composition-order bug in
  SQLAlchemy's `nulls_last()`/`desc()` interaction, not a security or logic issue — it did not
  touch the tenant-isolation predicate or any filter condition.

  Fix applied: changed the expression to `Item.published_at.desc().nulls_last()` — calling
  `.desc()` on the column first, then `.nulls_last()` on the resulting direction — which compiles
  to the correct `published_at DESC NULLS LAST`. This preserves the brief's intent exactly (most
  recent items first, items with no `published_at` sorted last, ties broken by `id DESC`) while
  producing valid SQL. Confirmed via the RED/GREEN evidence above: before the fix,
  `test_feed_excludes_other_users_private_items` and `test_get_item_refuses_other_users_private_item`
  failed with the SQL syntax error (the latter depends on `feed()` to look up an item id, per the
  test body); after the fix, both passed along with the other 7 tests.

No other deviations. No architectural questions arose — the brief's design (single
`visible_to` predicate, `websearch_to_tsquery` for malformed-input safety, conditional joins for
`kinds`/`subscribed_only`) was implementable as specified once the one SQL syntax bug was fixed.

---

## Fix Report (review round 2)

Reviewer approved `src/reachstore/query.py` as spec-compliant and correct (tenant isolation and
the `feed` ordering fix both verified). **No changes were made to `src/reachstore/query.py`** in
this round, per instruction. All changes below are test-only.

### Change 1 — replaced the confounded ranking test

**Finding accepted as correct.** `test_search_ranks_title_matches_above_body_matches` passed for
the wrong reason: "Release v2 indexing" contains "indexing" twice (once in title, once in body)
while "Postgres full text search" contains it once (body only), so raw term frequency alone
picked the same winner as field weighting would. Verified directly with the two original fixture
documents — see evidence below — but that check was for my own confirmation; the required
evidence is for the *new* fixture pair.

**Replacement test:** `test_title_match_outranks_body_match` in `tests/test_query_search.py`,
backed by a new helper `seed_field_weight_case`. It seeds exactly two items on their own source
(so no other fixture in the file, including `seed()`'s "indexing" documents, can interfere with a
query for "kestrel"):

- Inserted FIRST: `title="Kestrel release notes"`, `content_text="nothing relevant here"`
  (one occurrence of "kestrel", in the title)
- Inserted SECOND: `title="Nothing relevant"`, `content_text="kestrel appears once here"`
  (one occurrence of "kestrel", in the body)

Insertion order is deliberate and commented in the test: `search` orders by
`desc(rank), desc(Item.id)`, so the second-inserted (body) item has the higher id. If weighting
were broken and the ranks tied, the body item's higher id would let it win the tie-break and sort
first — making the test fail as intended, rather than passing by accident of insertion order.

**Required evidence — direct `ts_rank` comparison, weighted vs. unweighted, for the new fixture
pair.** Computed against the live `reachstore_test` database via a standalone script
(`/private/tmp/claude-501/-Users-dev2-Desktop-Testing/1c66e8e3-2c88-4d48-ab2f-501337401631/scratchpad/rank_check.py`,
not part of the repo), using literal `ts_rank(...)` calls — no table rows needed since `ts_rank`
operates on ad hoc tsvector/tsquery expressions:

Command: `.venv/bin/python /private/tmp/.../scratchpad/rank_check.py`

```
--- WEIGHTED (setweight A/B, matches production TSV_EXPRESSION) ---
title_item: 0.6079271
body_item: 0.24317084
title_item > body_item under weighting? True
--- UNWEIGHTED (plain concatenation, no setweight) ---
title_item: 0.06079271
body_item: 0.06079271
title_item > body_item without weighting? False
```

Under the real `setweight('A')`/`setweight('B')` expression, the title item wins clearly
(0.608 vs 0.243). Under a plain unweighted `to_tsvector(title) || to_tsvector(content_text)`
expression, the two ranks are **exactly tied** (0.0608 == 0.0608) — and per the insertion-order
argument above, a tie means the body item (higher id) would sort first, so the test would fail if
`setweight` were removed. This confirms the new fixture pair is not confounded: the test
discriminates specifically on field weighting, not on term frequency or any other factor.

### Change 2 — `before_id` pagination coverage

Added `test_feed_before_id_paginates_and_respects_isolation` and its helper
`setup_items_for_pagination` to `tests/test_query_isolation.py`. The helper seeds 5 shared items
plus one of Bob's private items, inserted in this order: `p1, p2, p3, <bob's private item>, p4,
p5`, all with the same `published_at` (so `feed`'s tie-break, `desc(Item.id)`, determines order).
This deliberately places Bob's private item's id *between* `p3` and `p4` — inside the id range a
`before_id` page would return if `visible_to` were not applied — so the test exercises real
composition between `before_id` and tenant isolation, not two independent checks that could each
pass while the composition is broken.

The test:
1. Calls `feed(session, user_id=alice.id)` with no `before_id` and asserts the full ordering is
   `p5, p4, p3, p2, p1` (descending id) and that Bob's private item is absent.
2. Takes the id of `p4` from that result as a cursor, calls
   `feed(session, user_id=alice.id, before_id=cursor.id)`, and asserts the page is exactly
   `p3, p2, p1`, that every returned item's id is less than the cursor's id, and that Bob's
   private item is still absent (it would otherwise appear, since its id is less than `p4`'s).

### Change 3 — `kinds` + `subscribed_only` combined

Added `test_search_kinds_and_subscribed_only_combine_with_and` to `tests/test_query_isolation.py`,
using the existing `setup_two_users_with_private_items` fixture. In that fixture Alice is
subscribed to the shared `rss` source but not to the `x_account` source, even though her own
private item ("alice secret") lives on the `x_account` source and is otherwise visible to her.

- `search(session, user_id=alice.id, q="alpha", kinds=["rss"], subscribed_only=True)` asserts
  the result is exactly `{"public news"}`.
- `search(session, user_id=alice.id, q="alpha", kinds=["x_account"], subscribed_only=True)`
  asserts the result is `[]` — proving the two joins are ANDed: Alice's own private item is
  visible to her and matches the `kinds` filter, but is correctly excluded because she is not
  subscribed to that source. If either join silently overrode the other, this second assertion
  would fail.

### Covering tests run

Command: `.venv/bin/pytest tests/test_query_isolation.py tests/test_query_search.py -v`

```
collecting ... collected 11 items

tests/test_query_isolation.py::test_feed_excludes_other_users_private_items PASSED [  9%]
tests/test_query_isolation.py::test_search_excludes_other_users_private_items PASSED [ 18%]
tests/test_query_isolation.py::test_get_item_refuses_other_users_private_item PASSED [ 27%]
tests/test_query_isolation.py::test_subscribed_only_limits_to_subscribed_sources PASSED [ 36%]
tests/test_query_isolation.py::test_search_kinds_and_subscribed_only_combine_with_and PASSED [ 45%]
tests/test_query_isolation.py::test_feed_before_id_paginates_and_respects_isolation PASSED [ 54%]
tests/test_query_search.py::test_search_matches_content_and_title PASSED [ 63%]
tests/test_query_search.py::test_search_ignores_non_matching_documents PASSED [ 72%]
tests/test_query_search.py::test_search_filters_by_kind PASSED           [ 81%]
tests/test_query_search.py::test_search_filters_by_since PASSED          [ 90%]
tests/test_query_search.py::test_title_match_outranks_body_match PASSED  [100%]

============================== 11 passed in 0.20s ==============================
```

Full suite:

Command: `.venv/bin/pytest`

```
collecting ... collected 21 items
[... all 21 PASSED ...]
============================== 21 passed in 0.23s ==============================
```

(Full per-test listing identical to the above 11 plus the pre-existing 10 from
`test_schema.py`/`test_store.py`, all PASSED — omitted here for brevity; captured in full in the
terminal output of this session.)

### Count discrepancy — flagging rather than fabricating

The review instructions expected "12 tests, all passing" for the two query files and "22/22" for
the full suite. The actual, correct counts are **11** and **21**. Walking the arithmetic: the
original two files had 9 tests (4 isolation + 5 search). Change 1 is an explicit one-for-one
replacement (delete one test, write one replacement) — net 0. Change 2 adds exactly one test.
Change 3 adds exactly one test. Net change: +2, giving 9 + 2 = 11 (and 19 + 2 = 21 for the full
suite, since Task 1/2's 10 tests are unchanged). I implemented every change exactly as specified
in the three numbered instructions and did not find a fourth new test implied anywhere in the
brief. I'm reporting this as a likely off-by-one in the reviewer's count rather than inventing an
unrequested test to force the numbers to match — happy to add a specific additional test if the
reviewer intended one beyond the three changes described.

### Files changed (this round)

- `tests/test_query_isolation.py` — added `test_search_kinds_and_subscribed_only_combine_with_and`,
  `setup_items_for_pagination`, and `test_feed_before_id_paginates_and_respects_isolation`.
- `tests/test_query_search.py` — replaced `test_search_ranks_title_matches_above_body_matches`
  with `seed_field_weight_case` + `test_title_match_outranks_body_match`.
- `src/reachstore/query.py` — **unchanged**, confirmed via `git diff --stat -- src/reachstore/query.py`
  (empty output) before committing.

Committed in `eaa632d` — "test: strengthen query layer test coverage per review".
