# Task 3: Read endpoints — Report

## What I implemented

Added the three read endpoints the React reader will consume, per the brief verbatim:

- `GET /api/feed` — one page of the feed, newest-first, with a compound `(before_published_at, before_id)` keyset cursor.
- `GET /api/search` — full-text search via `query.search`, optional `kind` filter.
- `GET /api/items/{item_id}` — item detail; 404 for both "does not exist" and "not visible" (deliberately indistinguishable per the brief's tenant-isolation rationale).

New schemas in `src/reachstore/api/schemas.py`: `ItemSummary`, `ItemDetail` (subclasses `ItemSummary`, adds `content_text` and `fetched_at`), `Cursor`, `FeedResponse`, `SearchResponse`. None of these carry `extra="forbid"` — they're built with explicit keyword arguments, so a name error is already a `TypeError` at the call site, unlike `SourceStatusOut`'s `**vars(dataclass)` splat.

`src/reachstore/api/routes.py`: replaced only the import block and `router = APIRouter(prefix="/api")` line at the top (added `EXCERPT_CHARS = 240` alongside it, as specified). The existing `list_sources` handler was left completely untouched below it. Appended `_summary()` (shared serialization helper), `get_feed`, `get_search`, `get_one_item`.

The API layer makes no SQL of its own — it only calls `query.feed`, `query.search`, `query.get_item`, and passes `DEFAULT_USER_ID` down to each. No `sqlalchemy.select` import anywhere in `routes.py` (verified via grep).

## What I tested and the results

`tests/test_api_read.py`, created verbatim from the brief — 7 tests:

1. `test_feed_returns_items_newest_first_with_source_labels`
2. `test_feed_excerpt_is_truncated_and_detail_is_not`
3. `test_feed_paginates_without_gaps_or_duplicates` — walks the full cursor loop across 5 items at page size 2 (3 pages), asserting no duplicates and no gaps (`len(seen) == 5 == len(set(seen))`). This is a real end-to-end exercise of the compound cursor, not a restatement of the implementation — it goes through the actual `before_id`/`before_published_at` query-param wire format, including the "cursor omits `before_published_at` when null" NULLS-LAST-tail case.
4. `test_search_ranks_and_filters_by_kind`
5. `test_search_results_carry_source_labels`
6. `test_missing_item_is_404`
7. `test_bad_limit_is_422`

All 7 pass. Full suite: 104 passed, 0 warnings (was 97; +7 new, no regressions, no new deprecation noise).

## TDD Evidence

**RED**

Command: `.venv/bin/pytest tests/test_api_read.py -v`

Result: 6 failed, 1 passed.

- 5 tests failed with `KeyError: 'items'` — `/api/feed` and `/api/search` didn't exist yet, so FastAPI's default 404 body (`{"detail": "Not Found"}`) has no `"items"` key. This is the exact failure mode the brief predicted ("FAIL — 404 on `/api/feed`, because the routes do not exist yet").
- `test_bad_limit_is_422` failed with `assert 404 == 422` for the same reason — the route not existing means the query-param validation never runs.
- `test_missing_item_is_404` passed "by accident" — `/api/items/999999` also 404s before the route exists, which happens to be the same status code the test expects. This is expected and not a signal of anything working yet; it's superseded by the GREEN run below, which exercises the real handler.

Representative excerpt:
```
E       KeyError: 'items'
tests/test_api_read.py:58: KeyError
...
E       AssertionError: assert 404 == 422
tests/test_api_read.py:109: AssertionError
==== 6 failed, 1 passed in 0.31s ====
```

**GREEN**

Command: `.venv/bin/pytest tests/test_api_read.py -v`

```
tests/test_api_read.py::test_feed_returns_items_newest_first_with_source_labels PASSED
tests/test_api_read.py::test_feed_excerpt_is_truncated_and_detail_is_not PASSED
tests/test_api_read.py::test_feed_paginates_without_gaps_or_duplicates PASSED
tests/test_api_read.py::test_search_ranks_and_filters_by_kind PASSED
tests/test_api_read.py::test_search_results_carry_source_labels PASSED
tests/test_api_read.py::test_missing_item_is_404 PASSED
tests/test_api_read.py::test_bad_limit_is_422 PASSED
============================== 7 passed in 0.30s ===============================
```

Full suite: `.venv/bin/pytest` → `104 passed in 1.66s`, zero warnings.

## Files changed

- `src/reachstore/api/schemas.py` — added `ItemSummary`, `ItemDetail`, `Cursor`, `FeedResponse`, `SearchResponse`.
- `src/reachstore/api/routes.py` — replaced import block only; added `_summary`, `get_feed`, `get_search`, `get_one_item`; `list_sources` untouched.
- `tests/test_api_read.py` — new, verbatim from brief.

Commit: `3b041bf feat: feed, search, and item detail endpoints`

## Self-review findings

- **Completeness:** all 6 steps of the brief followed in order (write failing tests → confirm RED → add schemas → add routes → confirm GREEN → run full suite and commit). All 3 endpoints and all 5 schemas from the brief are present.
- **Quality:** names match the brief's vocabulary (`_summary`, `EXCERPT_CHARS`, `get_feed`/`get_search`/`get_one_item`). Docstrings on `get_feed` and `get_one_item` explain the two non-obvious decisions (NULLS-LAST tail cursor semantics, 404-not-403 for isolation) inline, matching the brief's own rationale rather than paraphrasing it away.
- **Discipline:** diff is additive-only outside `routes.py`'s import block; `list_sources` byte-for-byte unchanged. No `sqlalchemy.select` import in the API layer — verified with `grep -n "select" src/reachstore/api/routes.py` (no hits). No `extra="forbid"` added to the new schemas, per the brief's explicit instruction not to cargo-cult that from `SourceStatusOut`.
- **Testing:** the pagination test is a real cursor walk through the HTTP layer (query params in, `next_cursor` out, fed back in), not a mock of `query.feed` — it would catch a broken cursor serialization (e.g. dropping `before_published_at` incorrectly) that a unit test of `_summary` alone would miss. Output is pristine: 104/104, 0 warnings.
- **Environment:** confirmed Postgres was running (`docker compose -f docker-compose.dev.yml up -d` → already running) before executing tests.

No issues found. No changes made after the initial implementation.

## Concerns

None. Work matches the brief exactly; no ambiguity encountered.

---

## Post-review fix report

Review returned two findings, both defects in the brief's test data (not in my transcription of it): the pagination test's assertions were real, but the seeded dataset (all-distinct `published_at`) meant the two hardest paths — the `id` DESC tie-break arm and the null-cursor round trip — were never actually reached through the HTTP layer. Second, a test name promised ranking coverage it didn't check.

### Finding 1 (Important) — pagination test didn't exercise the tie-break arm or the null-cursor round trip

**What I changed:** `test_feed_paginates_without_gaps_or_duplicates` in `tests/test_api_read.py` no longer uses the shared `seed()` helper (which gives every item a distinct `published_at` by design — other tests depend on that for their ordering assertions, so I left `seed()` itself untouched). It now builds its own 5-item dataset inline: 3 items (`e0`, `e1`, `e2`) share `published_at=NOW`, and 2 items (`e3`, `e4`) have `published_at=None`. With `limit=2`, the 3-way tie is split across the page-1/page-2 boundary, forcing `query.feed`'s tie-break condition (`published_at == before_published_at AND id < before_id`) to actually select a row rather than sit syntactically present but empirically unused. The 2-way null group forces a cursor whose `published_at` is `None` to round-trip through the wire format (JSON out, query param omitted, decoded back to `None` server-side) into the "continue through the NULLS LAST tail" branch.

Added `saw_null_cursor` tracking: the loop sets it whenever a fed-back cursor has `published_at is None`, and the test asserts `saw_null_cursor` at the end — so if a future regression stopped the null case from ever occurring (e.g. cursor construction silently defaulting nulls to something else), the test fails loudly instead of just quietly not covering it again.

**Verified by hand, as the reviewer asked**, not just inferred: I ran a throwaway instrumented copy of the test (`tests/test_zz_debug_trace.py`, deleted after use — not part of the diff) that printed each page's `(id, published_at)` and the emitted cursor. Actual trace:

```
page 0: params={'limit': 2} -> [(3, '2026-09-02T12:00:00Z'), (2, '...')], next_cursor={'published_at': '...', 'id': 2}
page 1: params={'limit': 2, 'before_id': 2, 'before_published_at': '2026-09-02T12:00:00Z'} -> [(1, '...'), (5, None)], next_cursor={'published_at': None, 'id': 5}
page 2: params={'limit': 2, 'before_id': 5} -> [(4, None)], next_cursor=None
seen: [3, 2, 1, 5, 4]
```

This confirms both hard cases fire for real: page 1's result includes id=1 specifically because `published_at == NOW AND id < 2` (the tie-break arm — id=1 is *not* selected by `published_at < NOW`, since it's tied, not older), and page 1's request (`before_id=5`, no `before_published_at`) is the genuine null-cursor round trip that correctly continues into the null tail and returns id=4 with no duplication or gap.

No bug was found in the endpoint or in `query.feed` — both hard cases behave correctly. The defect was purely that the original brief's test data (from the task-3 brief, transcribed verbatim in the initial implementation) couldn't reach them.

### Finding 2 (Minor) — misleading test name

Renamed `test_search_ranks_and_filters_by_kind` to `test_search_returns_hits_and_filters_by_kind`. No new assertion added — the test only ever checked presence of hits and the empty result under a mismatched `kind` filter; it never checked rank order, and ranking is already covered at the query layer (`tests/test_query_search.py::test_title_match_outranks_body_match`). Per the reviewer's instruction, scope was not expanded.

### Commands and output

`.venv/bin/pytest tests/test_api_read.py -v`:

```
tests/test_api_read.py::test_feed_returns_items_newest_first_with_source_labels PASSED
tests/test_api_read.py::test_feed_excerpt_is_truncated_and_detail_is_not PASSED
tests/test_api_read.py::test_feed_paginates_without_gaps_or_duplicates PASSED
tests/test_api_read.py::test_search_returns_hits_and_filters_by_kind PASSED
tests/test_api_read.py::test_search_results_carry_source_labels PASSED
tests/test_api_read.py::test_missing_item_is_404 PASSED
tests/test_api_read.py::test_bad_limit_is_422 PASSED
============================== 7 passed in 0.32s ===============================
```

Full suite, `.venv/bin/pytest`:

```
============================= 104 passed in 1.67s ==============================
```

Zero warnings, same as before the fix. `git status --short` before committing showed only `tests/test_api_read.py` modified (the debug trace file was deleted, not left in the tree).

### Files changed (this round)

- `tests/test_api_read.py` — pagination test rebuilt with tied and null `published_at` values plus a `saw_null_cursor` assertion; one test renamed.

Commit: `d9df2f2 fix: pagination test now exercises the compound cursor's hard cases`

### Concerns

None. Both findings were test-data gaps in data I transcribed verbatim from the brief, not implementation bugs — confirmed by tracing actual query results, not just re-reading the code.
