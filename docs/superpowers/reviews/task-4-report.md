# Task 4 Report: Adapter contract and RSS adapter

## What I implemented

1. **`src/reachstore/adapters/base.py`** — appended below the existing `NormalizedItem` dataclass (unmodified, unmoved), exactly the brief's Step 1 code:
   - `AdapterError(RuntimeError)`
   - `HttpFetcher` protocol (`get(url: str, *, timeout: int) -> str`)
   - `CommandRunner` protocol (`run(args: list[str], *, timeout: int) -> str`)
   - `Adapter` protocol (`kind: str`, `tier: int`, `fetch(identifier: str, since: datetime | None) -> list[NormalizedItem]`)
   - `HttpxFetcher` — production HTTP fetcher wrapping `httpx.get`
   - `SubprocessRunner` — production command runner wrapping `subprocess.run`, raising `AdapterError` on non-zero exit

2. **`tests/fixtures/rss_sample.xml`** — created exactly as given in the brief (two-item RSS 2.0 feed).

3. **`tests/test_adapter_rss.py`** — created exactly as given in the brief: `FakeHttp` test double, an `adapter` fixture using `fixtures_dir`, and 6 tests (kind/tier, entry count, field mapping, `since` filtering, missing-author handling, unparseable-body error).

4. **`src/reachstore/adapters/rss.py`** — created exactly as given in the brief:
   - `_to_datetime(parsed: struct_time | None) -> datetime | None` — attaches `tzinfo=UTC` to feedparser's naive `struct_time`, per the "no wall-clock reads / timezone-aware UTC" constraint.
   - `RssAdapter(http: HttpFetcher, timeout: int = 120)` with `kind = "rss"`, `tier = 1`.
   - `fetch(identifier, since)`: calls `http.get(identifier, timeout=self._timeout)`, parses with `feedparser.parse`, raises `AdapterError` if `feed.entries` is empty (feedparser never raises on garbage input — it sets `bozo` and returns empty entries instead), then maps each entry to a `NormalizedItem`. The `since` filter only drops an entry when `published is not None and published < since` — entries with no parseable date are never silently dropped, matching the brief's exact semantics and the task's explicit warning about this.
   - No imports of `sqlalchemy`, `httpx`, or `subprocess` — only `feedparser` and the injected `HttpFetcher`.

## TDD Evidence

### RED

Command: `.venv/bin/pytest tests/test_adapter_rss.py -v`

Run **before** `src/reachstore/adapters/rss.py` existed (only `base.py`, the fixture, and the test file were in place):

```
============================= test session starts ==============================
platform darwin -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- /Users/dev2/Desktop/Testing/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/dev2/Desktop/Testing
configfile: pyproject.toml
plugins: cov-7.1.0, anyio-4.14.2
collecting ... collected 0 items / 1 error

==================================== ERRORS ====================================
__________________ ERROR collecting tests/test_adapter_rss.py __________________
ImportError while importing test module '/Users/dev2/Desktop/Testing/tests/test_adapter_rss.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
.venv/lib/python3.12/site-packages/_pytest/python.py:508: in importtestmodule
    mod = import_path(
.venv/lib/python3.12/site-packages/_pytest/pathlib.py:596: in import_path
    importlib.import_module(module_name)
../../.local/share/uv/python/cpython-3.12.13-macos-aarch64-none/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
<frozen importlib._bootstrap>:1387: in _gcd_import
<frozen importlib._bootstrap>:1360: in _find_and_load
<frozen importlib._bootstrap>:1331: in _find_and_load_unlocked
<frozen importlib._bootstrap>:935: in _load_unlocked
.venv/lib/python3.12/site-packages/_pytest/assertion/rewrite.py:188: in exec_module
    exec(co, module.__dict__)
tests/test_adapter_rss.py:6: in <module>
    from reachstore.adapters.rss import RssAdapter
E   ModuleNotFoundError: No module named 'reachstore.adapters.rss'
=========================== short test summary info ============================
ERROR tests/test_adapter_rss.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
=============================== 1 error in 0.07s ===============================
```

This is exactly the expected RED failure per the brief's Step 4 (`ModuleNotFoundError: No module named 'reachstore.adapters.rss'`) — the missing module, not a missing protocol in `base.py` (which was already in place per the brief's intended step ordering).

### GREEN

Command: `.venv/bin/pytest tests/test_adapter_rss.py -v`

Run **after** implementing `src/reachstore/adapters/rss.py`:

```
============================= test session starts ==============================
platform darwin -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- /Users/dev2/Desktop/Testing/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/dev2/Desktop/Testing
configfile: pyproject.toml
plugins: cov-7.1.0, anyio-4.14.2
collecting ... collected 6 items

tests/test_adapter_rss.py::test_kind_and_tier PASSED                     [ 16%]
tests/test_adapter_rss.py::test_parses_all_entries PASSED                [ 33%]
tests/test_adapter_rss.py::test_maps_fields_correctly PASSED             [ 50%]
tests/test_adapter_rss.py::test_since_filters_older_entries PASSED       [ 66%]
tests/test_adapter_rss.py::test_missing_author_is_none PASSED            [ 83%]
tests/test_adapter_rss.py::test_unparseable_body_raises_adapter_error PASSED [100%]

============================== 6 passed in 0.03s ===============================
```

Output is pristine — no warnings, no deprecation notices.

## Full-suite result before committing

Command: `.venv/bin/pytest -v`

```
collecting ... collected 27 items

tests/test_adapter_rss.py::test_kind_and_tier PASSED
tests/test_adapter_rss.py::test_parses_all_entries PASSED
tests/test_adapter_rss.py::test_maps_fields_correctly PASSED
tests/test_adapter_rss.py::test_since_filters_older_entries PASSED
tests/test_adapter_rss.py::test_missing_author_is_none PASSED
tests/test_adapter_rss.py::test_unparseable_body_raises_adapter_error PASSED
tests/test_query_isolation.py::test_feed_excludes_other_users_private_items PASSED
tests/test_query_isolation.py::test_search_excludes_other_users_private_items PASSED
tests/test_query_isolation.py::test_get_item_refuses_other_users_private_item PASSED
tests/test_query_isolation.py::test_subscribed_only_limits_to_subscribed_sources PASSED
tests/test_query_isolation.py::test_search_kinds_and_subscribed_only_combine_with_and PASSED
tests/test_query_isolation.py::test_feed_before_id_paginates_and_respects_isolation PASSED
tests/test_query_search.py::test_search_matches_content_and_title PASSED
tests/test_query_search.py::test_search_ignores_non_matching_documents PASSED
tests/test_query_search.py::test_search_filters_by_kind PASSED
tests/test_query_search.py::test_search_filters_by_since PASSED
tests/test_query_search.py::test_title_match_outranks_body_match PASSED
tests/test_schema.py::test_all_tables_exist PASSED
tests/test_schema.py::test_items_has_generated_tsvector_column PASSED
tests/test_schema.py::test_tsvector_index_exists PASSED
tests/test_store.py::test_upsert_inserts_new_items PASSED
tests/test_store.py::test_upsert_is_idempotent PASSED
tests/test_store.py::test_upsert_writes_raw_payload_to_disk PASSED
tests/test_store.py::test_upsert_records_owner_for_private_items PASSED
tests/test_store.py::test_same_external_id_different_sources_are_distinct PASSED
tests/test_store.py::test_upsert_writes_distinct_raw_files_for_identical_content PASSED
tests/test_store.py::test_upsert_does_not_rewrite_raw_file_on_replay PASSED

============================== 27 passed in 0.28s ===============================
```

27/27 (21 existing from Tasks 1-3 + 6 new). Re-verified again after the commit with the same result.

## Files changed

- Modified: `src/reachstore/adapters/base.py` (appended `AdapterError`, `HttpFetcher`, `CommandRunner`, `Adapter`, `HttpxFetcher`, `SubprocessRunner` below `NormalizedItem`, unchanged otherwise)
- Created: `src/reachstore/adapters/rss.py`
- Created: `tests/fixtures/rss_sample.xml`
- Created: `tests/test_adapter_rss.py`

## Self-review findings

- **Completeness:** all brief items implemented — three protocols, two production implementations, `AdapterError`, `RssAdapter`, fixture, and all 6 tests.
- **Contract quality:** `HttpFetcher.get`, `CommandRunner.run`, and `Adapter.fetch` signatures match the brief verbatim, including parameter names and keyword-only `timeout`.
- **Isolation:** `rss.py` imports only `feedparser`, `from __future__ import annotations`, `datetime`/`UTC`, `struct_time`, and `reachstore.adapters.base` symbols. No `sqlalchemy`, `httpx`, or `subprocess` import in `rss.py`. `httpx`/`subprocess` are imported only in `base.py`, inside `HttpxFetcher`/`SubprocessRunner`, which is where the brief places them.
- **Quality:** names match the brief's naming (`RssAdapter`, `kind`, `tier`, `_to_datetime`). No unnecessary complexity added.
- **Discipline (YAGNI):** implemented only what the brief specified — no retry logic, no logging, no extra adapters, no additional helper methods beyond `_to_datetime`.
- **Testing:** tests exercise the real `feedparser.parse` against the committed fixture file (no mocking of the parser itself) — only the HTTP transport is faked via `FakeHttp`, per the dependency-injection rule. Test output has no warnings/noise.
- One deliberate deviation from the brief's literal Step 1 code layout: the brief's Step-1 code block places `import subprocess`, `from typing import Protocol, runtime_checkable`, and `import httpx` mid-file (after `NormalizedItem`) rather than at the top of `base.py`. I followed the brief exactly as given (append verbatim below `NormalizedItem`), since the brief explicitly says to append this block below the dataclass and gives that exact code. This is intentional per the brief's instructions, not an oversight.

## Issues / deviations from the brief

- **Commit staging:** the brief's Step 7 says `git add -A && git commit -m "..."`. At task start, `git status` showed a pre-existing unstaged, unrelated modification to `docs/superpowers/plans/2026-08-13-core-store-and-tier1-collection.md` (documentation amendments referencing already-committed Task 3 commits `c5b097c` and `eaa632d`, left over from a prior session). This predates my work and is out of scope for Task 4. Per the repo-wide git safety protocol ("prefer adding specific files by name rather than using `git add -A`"), I staged only the four Task 4 files by name (`src/reachstore/adapters/base.py`, `src/reachstore/adapters/rss.py`, `tests/test_adapter_rss.py`, `tests/fixtures/rss_sample.xml`) instead of running a blanket `git add -A`, so the unrelated doc change was not swept into this commit. It remains unstaged in the working tree for whoever should own that commit. No other deviations.

---

## Fix Report: Review Round 1

The coordinator relayed a review with two Important findings (both inherited from the brief's literal code, which the human ruled govern over the plan) plus three tests to add.

### Finding 1 — imports sit mid-file in `base.py` (E402)

**Fix applied.** Moved `import subprocess`, `from typing import Protocol, runtime_checkable` (merged into the existing `from typing import Any` line as `from typing import Any, Protocol, runtime_checkable`), and `import httpx` to the top of `src/reachstore/adapters/base.py`, consolidated with the pre-existing imports. `NormalizedItem` was **not** moved — it stays immediately after the imports, above the protocols, exactly where it was. Only the three import statements moved.

Resulting import block at the top of `base.py`:
```python
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

import httpx
```

### Finding 2 — empty-but-valid feed treated as fatal error

**Premise verified empirically first, as requested.** Ran a standalone script against the actual installed `feedparser` (6.0.14):

```python
import feedparser

# Case 1: garbage body used by the existing test_unparseable_body_raises_adapter_error
feed1 = feedparser.parse("this is not a feed at all")
# feed1.bozo        -> 1   (truthy)
# feed1.bozo_exception -> <unknown>:2:0: syntax error
# feed1.entries     -> []

# Case 2: well-formed <channel> with title/link but zero <item> elements
feed2 = feedparser.parse(<valid empty RSS 2.0 feed>)
# feed2.bozo        -> False
# feed2.bozo_exception -> None
# feed2.entries     -> []
```

**Reported values (as requested):**
- Garbage body (`"this is not a feed at all"`): `feed.bozo` is **truthy (`1`)**. The proposed fix does NOT break `test_unparseable_body_raises_adapter_error` — that entry still raises `AdapterError` via the `feed.bozo` branch.
- Valid feed with `<channel>` but no `<item>` elements: `feed.bozo` is **falsy (`False`)**. The proposed fix correctly returns `[]` for this case instead of raising.

Both values match what the reviewer predicted. Premise confirmed — proceeded with the fix as specified.

**Fix applied** to `src/reachstore/adapters/rss.py`, `fetch()`:
```python
feed = feedparser.parse(body)
if not feed.entries:
    if feed.bozo:
        raise AdapterError(f"could not parse {identifier}: {feed.bozo_exception}")
    return []
```
This also surfaces `feed.bozo_exception` in the error message, making genuine parse failures diagnosable (previously the message was just `"no entries parsed from {identifier}"` with no cause).

### Three new tests added

Two new committed fixtures, matching the existing fixture-file convention (no inline XML):

- **`tests/fixtures/rss_edge_cases.xml`** — valid RSS 2.0 feed, two items: one with `<pubDate>Tue, 12 Aug 2026 09:30:00 +0800</pubDate>` (non-UTC offset), one with no `<pubDate>` element at all.
- **`tests/fixtures/rss_empty.xml`** — valid RSS 2.0 feed, `<channel>` with title/link, zero `<item>` elements.

Verified both fixtures' actual feedparser behavior before writing assertions:
- `rss_edge_cases.xml`: `bozo=False`, 2 entries. The offset entry's `published_parsed` came back as `struct_time(tm_year=2026, tm_mon=8, tm_mday=12, tm_hour=1, tm_min=30, ...)` — i.e., feedparser already normalized `09:30 +0800` to `01:30 UTC` before `_to_datetime` even runs. This confirms the reviewer's claim that feedparser normalizes to UTC internally, and confirms `datetime(2026, 8, 12, 1, 30, tzinfo=UTC)` is the correct expected value (09:30 − 8h = 01:30). The undated entry's `published_parsed` is `None`, as expected.
- `rss_empty.xml`: `bozo=False`, 0 entries — matches Finding 2's Case 2 exactly.

Added to `tests/test_adapter_rss.py` (existing 6 tests left unmodified):

```python
def test_non_utc_offset_is_converted_to_utc(fixtures_dir):
    adapter = RssAdapter(FakeHttp((fixtures_dir / "rss_edge_cases.xml").read_text()))
    items = adapter.fetch("https://example.com/feed", None)
    dated = next(i for i in items if i.title == "Dated with offset")
    assert dated.published_at == datetime(2026, 8, 12, 1, 30, tzinfo=UTC)


def test_undated_entry_survives_since_filter(fixtures_dir):
    adapter = RssAdapter(FakeHttp((fixtures_dir / "rss_edge_cases.xml").read_text()))
    items = adapter.fetch("https://example.com/feed", datetime(2026, 8, 13, tzinfo=UTC))
    assert [i.title for i in items] == ["Undated post"]


def test_empty_but_valid_feed_returns_no_items(fixtures_dir):
    adapter = RssAdapter(FakeHttp((fixtures_dir / "rss_empty.xml").read_text()))
    items = adapter.fetch("https://example.com/feed", None)
    assert items == []
```

`test_undated_entry_survives_since_filter` uses `since = datetime(2026, 8, 13, tzinfo=UTC)`, which is later than the dated entry's `2026-08-12 01:30 UTC`, so the dated entry is filtered out by the `since` predicate while the undated entry (no parseable date) survives — proving undated entries are never silently dropped.

### Covering tests run

**Command:** `.venv/bin/pytest tests/test_adapter_rss.py -v`

```
============================= test session starts ==============================
platform darwin -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- /Users/dev2/Desktop/Testing/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/dev2/Desktop/Testing
configfile: pyproject.toml
plugins: cov-7.1.0, anyio-4.14.2
collecting ... collected 9 items

tests/test_adapter_rss.py::test_kind_and_tier PASSED                     [ 11%]
tests/test_adapter_rss.py::test_parses_all_entries PASSED                [ 22%]
tests/test_adapter_rss.py::test_maps_fields_correctly PASSED             [ 33%]
tests/test_adapter_rss.py::test_since_filters_older_entries PASSED       [ 44%]
tests/test_adapter_rss.py::test_missing_author_is_none PASSED            [ 55%]
tests/test_adapter_rss.py::test_unparseable_body_raises_adapter_error PASSED [ 66%]
tests/test_adapter_rss.py::test_non_utc_offset_is_converted_to_utc PASSED [ 77%]
tests/test_adapter_rss.py::test_undated_entry_survives_since_filter PASSED [ 88%]
tests/test_adapter_rss.py::test_empty_but_valid_feed_returns_no_items PASSED [100%]

============================== 9 passed in 0.03s ===============================
```

9/9 passing, pristine output, including all 6 original tests unmodified.

**Command:** `.venv/bin/pytest -v` (full suite)

```
collecting ... collected 30 items

tests/test_adapter_rss.py::test_kind_and_tier PASSED
tests/test_adapter_rss.py::test_parses_all_entries PASSED
tests/test_adapter_rss.py::test_maps_fields_correctly PASSED
tests/test_adapter_rss.py::test_since_filters_older_entries PASSED
tests/test_adapter_rss.py::test_missing_author_is_none PASSED
tests/test_adapter_rss.py::test_unparseable_body_raises_adapter_error PASSED
tests/test_adapter_rss.py::test_non_utc_offset_is_converted_to_utc PASSED
tests/test_adapter_rss.py::test_undated_entry_survives_since_filter PASSED
tests/test_adapter_rss.py::test_empty_but_valid_feed_returns_no_items PASSED
tests/test_query_isolation.py::test_feed_excludes_other_users_private_items PASSED
tests/test_query_isolation.py::test_search_excludes_other_users_private_items PASSED
tests/test_query_isolation.py::test_get_item_refuses_other_users_private_item PASSED
tests/test_query_isolation.py::test_subscribed_only_limits_to_subscribed_sources PASSED
tests/test_query_isolation.py::test_search_kinds_and_subscribed_only_combine_with_and PASSED
tests/test_query_isolation.py::test_feed_before_id_paginates_and_respects_isolation PASSED
tests/test_query_search.py::test_search_matches_content_and_title PASSED
tests/test_query_search.py::test_search_ignores_non_matching_documents PASSED
tests/test_query_search.py::test_search_filters_by_kind PASSED
tests/test_query_search.py::test_search_filters_by_since PASSED
tests/test_query_search.py::test_title_match_outranks_body_match PASSED
tests/test_schema.py::test_all_tables_exist PASSED
tests/test_schema.py::test_items_has_generated_tsvector_column PASSED
tests/test_schema.py::test_tsvector_index_exists PASSED
tests/test_store.py::test_upsert_inserts_new_items PASSED
tests/test_store.py::test_upsert_is_idempotent PASSED
tests/test_store.py::test_upsert_writes_raw_payload_to_disk PASSED
tests/test_store.py::test_upsert_records_owner_for_private_items PASSED
tests/test_store.py::test_same_external_id_different_sources_are_distinct PASSED
tests/test_store.py::test_upsert_writes_distinct_raw_files_for_identical_content PASSED
tests/test_store.py::test_upsert_does_not_rewrite_raw_file_on_replay PASSED

============================== 30 passed in 0.28s ===============================
```

30/30 (21 from Tasks 1-3 + 9 in `test_adapter_rss.py`). Re-verified again after the commit with the same result.

### Files changed in this round

- Modified: `src/reachstore/adapters/base.py` (imports moved to top; `NormalizedItem` position unchanged)
- Modified: `src/reachstore/adapters/rss.py` (empty-entries handling now branches on `feed.bozo`)
- Modified: `tests/test_adapter_rss.py` (3 new tests appended; existing 6 untouched)
- Created: `tests/fixtures/rss_edge_cases.xml`
- Created: `tests/fixtures/rss_empty.xml`

### Commit

`f4ea3af` — "fix: address code review findings in RSS adapter" (separate commit from `3c2352c`, staged by filename per the git safety protocol; the coordinator confirmed the previously-flagged stray `docs/superpowers/plans/...md` change was theirs and has since been committed separately, so it did not need to be excluded again here).

### Issues / concerns from this round

None. Both findings' premises were verified empirically before applying fixes, per the reviewer's explicit instruction to stop and report if the premises didn't hold — they held exactly as predicted. No deviations from the requested fixes or test specs.
