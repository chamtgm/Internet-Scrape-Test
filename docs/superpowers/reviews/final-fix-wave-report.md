# Final Fix Wave Report — feat/core-store-tier1

Applied all 12 findings from the whole-branch review in order: F10 first, then
the two Criticals (F1, F2), then the Importants (F3–F9), then the Minors
(F11), then the F12 real-`gh` verification. Six commits, grouped as
instructed. Full suite went from 64 passing to 86 passing and stayed green
before every commit.

Baseline before any changes: `.venv/bin/pytest -q` → **64 passed in 0.41s**.
Final: **86 passed in 1.44s** (working tree clean).

---

## F10 — conftest.py safety guard (CRITICAL, done first)

**Changed:** `tests/conftest.py`. Extracted a `_guard_test_database(test_url,
primary_url)` helper called at the top of the `engine` fixture, before `DROP
SCHEMA public CASCADE`. It `pytest.fail`s if `test_database_url ==
database_url`, or if the database name (last path segment, query string
stripped) does not end in `_test`.

**Covering test:** `tests/test_conftest_safety.py` (new file), three tests
calling `_guard_test_database` directly rather than going through the
session-scoped `engine` fixture (which backs every other test and only runs
once per session):
- rejects test_url == primary_url
- rejects a database name not ending in `_test`
- allows a genuine `..._test` url that differs from primary

**Discriminating how:** the function did not exist before this change. `git
show HEAD:tests/conftest.py | grep -c _guard_test_database` → `0`, confirmed
before writing the test. Importing it from the pre-fix file would raise
`ImportError`, which is why the test is unconditionally a valid regression
guard.

**Command/output:**
```
.venv/bin/pytest tests/test_conftest_safety.py -v
...
tests/test_conftest_safety.py::test_guard_rejects_test_url_identical_to_primary_url PASSED
tests/test_conftest_safety.py::test_guard_rejects_database_name_not_ending_in_test PASSED
tests/test_conftest_safety.py::test_guard_allows_a_genuine_test_database PASSED
3 passed in 0.00s
```

This repo's actual `.env` already satisfies the guard (`reachstore` vs.
`reachstore_test`), so no other test's behavior changed.

**Commit:** `a1fdfa1 fix: refuse to drop the test schema unless the DB is clearly a test DB (F10)`

---

## F1 — since watermark drops items forever (CRITICAL)

**Changed:** `src/reachstore/collect.py`. `collect_source` now calls
`adapter.fetch(source.identifier, None)` unconditionally, and no longer calls
`query.last_run_started_at(session, source.id, "success")` to compute a
watermark. Left a comment explaining why, and that `since` stays in the
`Adapter` protocol and every adapter for Plan 3's paginated adapters.

**Note on the plan's suggestion:** the fix description said "If
`query.last_run_started_at` becomes unused after this, leave it in query.py
... Add a one-line comment." I checked: it does **not** become unused —
`should_attempt` (collect.py:47) still calls it with `status="failed"` to
compute backoff delay. So I did not add the "don't delete as dead code"
comment, since the premise (that it becomes dead code) doesn't hold. Flagging
this per the instruction to report when a fix's premise doesn't check out —
this one is a minor mismatch, not a wrong fix; the primary fix (pass `None`)
is applied exactly as specified.

**Covering test:** `tests/test_collect.py::test_collect_source_never_passes_a_since_watermark_to_the_adapter`.
Seeds a `success` fetch_run at `NOW - 1h`, then asserts
`adapter.received_since is None` after `collect_source`. Also gave
`StubAdapter` a `received_since` attribute recording what it was passed
(was previously accepted and silently ignored — the reason this bug survived
the per-task review).

**Pre-fix failure (captured by temporarily swapping in the old collect.py):**
```
AssertionError: assert datetime.datetime(2026, 8, 13, 11, 0, tzinfo=...) is None
 +  where datetime.datetime(2026, 8, 13, 11, 0, ...) = <StubAdapter>.received_since
```
i.e. the old code passed the prior run's `started_at` as `since`, exactly the
bug described.

**Commit:** `28f0b2a fix: stop passing a since watermark to adapters, it drops items permanently (F1)`

---

## F2 — feed() pagination duplicates/drops rows (CRITICAL, hardest item)

**Changed:** `src/reachstore/query.py::feed`.

**Signature decision:** changed the signature to `feed(session, *, user_id,
limit=50, before_id=None, before_published_at=None)`. I did **not** try to
preserve a `before_id`-only cursor as functionally meaningful, because that
shape is exactly the bug — matching the plan's permission to redesign freely
since `feed` has no CLI caller today. The two params are read together:
`before_id=None` means "first page"; once `before_id` is set,
`before_published_at` disambiguates two sort positions:
- non-`None`: general case, cursor row had a real timestamp
- `None`: the cursor row itself was in the NULLS LAST tail (a legitimate
  value, not "no cursor" — decided by `before_id`, not by
  `before_published_at`)

**Cursor logic** (explicit boolean expression, not `sqlalchemy.tuple_()`):
```python
if before_published_at is not None:
    stmt = stmt.where(or_(
        Item.published_at.is_(None),
        Item.published_at < before_published_at,
        and_(Item.published_at == before_published_at, Item.id < before_id),
    ))
else:
    stmt = stmt.where(Item.published_at.is_(None), Item.id < before_id)
```
**Why not `tuple_()`:** the plan suggested `sqlalchemy.tuple_()` row-value
comparison. I checked its semantics: SQL row-value comparison treats any NULL
component as making the whole comparison NULL (unknown), which is *not* the
same as "NULLS LAST" ordering (where NULL sorts as if it were the smallest
value). A raw `tuple_(published_at, id) < tuple_(cursor_ts, cursor_id)` would
silently misbehave for NULL rows. The explicit OR/AND above encodes the exact
`(published_at DESC NULLS LAST, id DESC)` "comes after" relation and is
verified against a real Postgres 16 instance in the NULL-tail test below.

**Covering tests** (`tests/test_query_isolation.py`):
1. `setup_items_for_pagination` — **rewritten** so `published_at` descends
   monotonically (`NOW`, `NOW-1h`, `NOW-2h`, ..., `NOW-4h`) while `id`
   ascends, matching "adapters emit newest-first → newest item gets the
   lowest id." Bob's private item is interleaved in the id range as before.
2. `test_feed_before_id_paginates_and_respects_isolation` — **updated** to
   pass the compound cursor and updated expected order (now genuinely
   published_at-descending, not an id-tiebreak artifact).
3. `test_feed_pagination_returns_every_item_exactly_once_in_order` (new) —
   pages through the full 5-item set at `limit=2`, asserts the concatenated
   titles equal the correct full order with **no duplicate ids**.
4. `test_feed_pagination_through_null_published_at_tail` (new) — 1 dated item
   + 3 undated items; walks pagination through the NULLS LAST tail at
   `limit=2`, exercising the `before_published_at is None` branch
   specifically.

**Pre-fix failure, captured two ways as instructed:**

a) Genuine logical failure (dup/drop), using the *old* `before_id`-only
   signature against the *old* query.py, with the *new* fixture (proves the
   bug is in the cursor logic, not just a signature mismatch) — via a scratch
   test file, run and then deleted:
```
AssertionError: assert ['page item 1', 'page item 2', 'page item 1'] == ['page item 1', 'page item 2', 'page item 3', 'page item 4', 'page item 5']
  At index 2 diff: 'page item 1' != 'page item 3'
  Right contains 2 more items, first extra item: 'page item 4'
```
Page 2 re-returned "page item 1" (already shown on page 1 — duplicate) and
never returned "page item 4" / "page item 5" (dropped forever). This matches
the review's description exactly: id-only cursor filtered on `id < 3`, which
excluded item4 (id=5) and item5 (id=6) even though they belong on page 2.

b) The actual committed test, run against `HEAD`'s query.py (no
   `before_published_at` param at all): fails with `TypeError` on the missing
   parameter, confirming the committed test is also discriminating against
   the exact pre-fix module.

**Command/output (post-fix):**
```
.venv/bin/pytest tests/test_query_isolation.py -v
...8 passed in 0.20s
```

**Commit:** `684428a fix: use a compound (published_at, id) keyset cursor in feed() (F2)`

---

## F3 — SubprocessRunner leaks two of three failure modes (IMPORTANT)

**Changed:** `src/reachstore/adapters/base.py::SubprocessRunner.run`. Wraps
the whole `subprocess.run` call: catches `subprocess.TimeoutExpired`,
`FileNotFoundError` (before `OSError`, since it's a subclass, for a distinct
"command not found" message), then `OSError`, each re-raised as
`AdapterError(...) from exc`. The existing non-zero-exit-code check is
unchanged.

**Also changed:** `src/reachstore/adapters/github.py::fetch` — uses
`release.get("id")` instead of `release["id"]`, raising `AdapterError` with
the malformed release's repr if `id` is absent.

**Covering tests:**
- `tests/test_adapter_base.py::test_subprocess_runner_wraps_missing_binary` —
  invokes a nonexistent binary name, asserts `AdapterError` with
  `__cause__` being `FileNotFoundError`.
- `tests/test_adapter_base.py::test_subprocess_runner_wraps_timeout` — runs
  `/bin/sleep 5` with `timeout=1`, asserts `AdapterError` with `__cause__`
  being `subprocess.TimeoutExpired`. Both local/offline, no network.
- `tests/test_adapter_github.py::test_release_missing_id_raises_adapter_error_not_key_error`

**Pre-fix failures (captured by swapping in old base.py/github.py):**
```
FAILED test_subprocess_runner_wraps_missing_binary - FileNotFoundError: [Errno 2] No such file or directory: 'this-binary-certainly-does-not-exist-xyz'
FAILED test_subprocess_runner_wraps_timeout - subprocess.TimeoutExpired: Command '['/bin/sleep', '5']' timed out after 1 seconds
FAILED test_release_missing_id_raises_adapter_error_not_key_error - KeyError: 'id'
```
Exactly the leaked-exception bug described — the old code did not catch
these at all, so they propagated raw instead of surfacing as `AdapterError`.

**Commit:** `87a1fc2 fix: adapter-contract fixes and consistency (F3, F5, F6, F8, F11)`

---

## F4 — source_health ignores user_id (IMPORTANT)

**Changed:** `src/reachstore/query.py::source_health` — removed the
`user_id` parameter entirely. Docstring now states plainly that this is a
deliberate global operator view (sources have no owner), and explains why it
is *not* scoped by `subscriptions` (no write path yet — would return empty
in any real deployment). `src/reachstore/cli.py::health` — dropped the
`--user-id` option to match.

**Existing tests deliberately updated (and why):**
- `tests/test_collect.py::test_source_health_reports_attention_state` —
  removed the now-pointless `User` creation and the `user_id=user.id` kwarg
  (also dropped the now-unused `User` import from that file). This test
  previously encoded the old, misleading signature; the fix requires
  removing the parameter, so the call site had to change.
- `tests/test_cli.py::test_health_lists_source_status` — invokes
  `["health"]` instead of `["health", "--user-id", "1"]`.

**Discriminating how:** both updated tests fail against the pre-fix code —
verified by temporarily swapping in the old `cli.py`/`query.py`:
```
tests/test_cli.py::test_health_lists_source_status FAILED
  assert 2 == 0   (SystemExit(2): unrecognized arguments — old CLI required --user-id)

tests/test_collect.py::test_source_health_reports_attention_state FAILED
  TypeError: source_health() missing 1 required keyword-only argument: 'user_id'
```

**Commit:** `5791443 fix: remove misleading user_id from source_health and clamp read limits (F4, F7)`

---

## F5 — RSS indexes teasers instead of articles (IMPORTANT)

**Changed:** `src/reachstore/adapters/rss.py`. New `_content_text(entry)`
helper: prefers `entry.content[0].value` (feedparser's exposure of
`<content:encoded>`) when present and non-empty, falls back to
`entry.get("summary", "")`. Verified empirically with feedparser 6.x that
`entry.content` is a list of dicts with a `value` key, and that Atom's
existing summary-backfill-from-content behavior is untouched (this path
never populates `entry.content` differently for Atom).

**Covering test:** `tests/test_adapter_rss.py::test_prefers_content_encoded_over_summary_teaser`,
new fixture `tests/fixtures/rss_content_encoded.xml` with both a short
`<description>` and a longer `<content:encoded>`. All 9 pre-existing RSS
tests kept passing unmodified (per the requirement).

**Pre-fix failure:**
```
AssertionError: assert 'full article body' in 'Short teaser only.'
```

**Commit:** `87a1fc2` (same commit as F3, adapter-contract group)

---

## F6 — RSS raw payload discards source bytes (IMPORTANT)

**Changed:** `src/reachstore/adapters/rss.py`. `raw` is now
`{"feed_xml": body, "entry_id": entry_id}` per item — `body` is the full,
verbatim upstream response text (identical across all items from one fetch),
`entry_id` is the same value used as `external_id`, letting a future
reprocessor re-parse the original XML and locate this entry within it.
`store.py` untouched, as required.

**Shape chosen:** `{"feed_xml": <str>, "entry_id": <str>}` — exactly the
shape suggested in the fix description. Accepted the storage cost of
duplicating the full feed body once per item (same tradeoff `github.py`
already makes per-release, scaled up since one feed fetch yields multiple
items) in exchange for genuine replayability.

**Existing test deliberately updated (and why):**
`tests/test_adapter_rss.py::test_maps_fields_correctly` asserted
`first.raw["link"] == "..."`, which directly encoded the old
`raw=dict(entry)` shape that F6 replaces. Updated to assert
`first.raw["entry_id"] == "https://example.com/posts/tsvector"` and that
`"<title>Understanding tsvector</title>" in first.raw["feed_xml"]` — proving
the new shape and that `feed_xml` is genuinely the raw upstream XML, not a
parsed structure.

**Pre-fix failure (temporarily swapped in old rss.py):**
```
KeyError: 'entry_id'
```

**Commit:** `87a1fc2` (adapter-contract group)

---

## F7 — unvalidated limit in feed()/search() (IMPORTANT)

**Changed:** `src/reachstore/query.py`. Added `MAX_LIMIT = 200` and a
`_clamp_limit(limit) -> max(1, min(limit, MAX_LIMIT))` helper; both `feed`
and `search` now call `.limit(_clamp_limit(limit))` instead of `.limit(limit)`.

**Covering tests** (`tests/test_query_search.py`, `tests/test_query_isolation.py`):
- `test_clamp_limit_boundaries` — direct unit coverage of the clamp math at
  `0`, `-1`, `-1000`, `1`, `MAX_LIMIT`, `MAX_LIMIT+1`, `10_000_000`.
- `test_search_with_negative_limit_does_not_raise_and_still_returns_a_result`
  / `test_feed_with_negative_limit_...` — integration proof against a real
  Postgres 16 that `limit=-1` no longer raises.
- Matching `limit=0` and huge-limit tests for both `feed` and `search`.

**Pre-fix failure (real Postgres error, captured by removing the clamp calls
while keeping F2/F4 fixes intact):**
```
sqlalchemy.exc.DataError: (psycopg.errors.InvalidRowCountInLimitClause) LIMIT must not be negative
[SQL: ... ORDER BY items.published_at DESC NULLS LAST, items.id DESC  LIMIT %(param_1)s::INTEGER]
[parameters: {'owner_user_id_1': 2, 'param_1': -1}]
```
This is the exact Postgres error the fix description names, reproduced
against the real dockerized Postgres 16.

**Commit:** `5791443` (query-layer group, with F4)

---

## F8 — GitHub timestamps can be naive (IMPORTANT)

**Changed:** `src/reachstore/adapters/github.py::_parse_iso`. After
`datetime.fromisoformat`, if `parsed.tzinfo is None`, attaches UTC via
`.replace(tzinfo=UTC)`.

**Covering test:** `tests/test_adapter_github.py::test_naive_published_at_is_treated_as_utc`,
using a fixture release with `"published_at": "2026-08-01T00:00:00"` (no
offset). Asserts the result equals the aware `datetime(2026, 8, 1, 0, 0,
tzinfo=UTC)` and that `tzinfo is not None`.

**Pre-fix failure:**
```
AssertionError: assert datetime.datetime(2026, 8, 1, 0, 0) == datetime.datetime(2026, 8, 1, 0, 0, tzinfo=datetime.timezone.utc)
```
(naive vs. aware — equality is `False`, not a raised `TypeError`, but clearly wrong.)

**Commit:** `87a1fc2` (adapter-contract group)

---

## F9 — add-source has no validation, is not idempotent (IMPORTANT)

**Changed:**
- `src/reachstore/query.py` — new `get_source(session, *, kind, identifier)
  -> Source | None`, a natural-key lookup. Added here (not a
  catch-`IntegrityError` approach in cli.py) to respect the Global Constraint
  that all SQL lives in `store.py`/`query.py`.
- `src/reachstore/cli.py::add_source` — validates `kind` against
  `sorted(build_default_registry().keys())` before touching the database;
  on an unknown kind, echoes the valid kinds and exits 1. Before inserting,
  checks `get_source(...)`; if a match exists, echoes "already registered"
  and returns (exit 0) instead of inserting and hitting the unique
  constraint.

**Covering tests** (`tests/test_cli.py`):
- `test_add_source_rejects_unknown_kind` — `add-source rrs ...` exits
  non-zero, `"rss"` appears in the valid-kinds message, no `Source` row
  created.
- `test_add_source_twice_is_idempotent` — two identical `add-source`
  invocations both exit 0, second prints "already registered", exactly one
  `Source` row exists.

**Pre-fix failures (temporarily swapped in old cli.py/query.py):**
```
test_add_source_rejects_unknown_kind: assert 0 != 0   (old CLI accepted any kind, exit 0)

test_add_source_twice_is_idempotent:
  assert 1 == 0
   +  where 1 = <Result IntegrityError('... duplicate key value violates unique
      constraint "uq_sources_kind_identifier" ...')>.exit_code
```
The second failure is the literal bare-traceback bug the fix describes.

**Commit:** `c874a5c fix: validate kind and make add-source idempotent (F9)`

---

## F11 — consistency and annotations (MINOR batch)

All items applied, in the `87a1fc2` adapter-contract commit:
- `-> None` added to `RssAdapter.__init__`, `GithubRepoAdapter.__init__`,
  `WebPageAdapter.__init__`.
- `tests/conftest.py`: `engine` fixture now returns
  `Generator[Engine, None, None]`, `session` fixture returns
  `Generator[Session, None, None]` (added `Engine`/`Session` imports and
  `collections.abc.Generator`).
- `web.py::fetch` now rejects any `identifier` not starting with `http://` or
  `https://`, raising `AdapterError` before any I/O. Covering tests:
  `test_rejects_identifier_that_is_not_an_http_url` (empty string) and
  `test_rejects_identifier_without_http_scheme` — both assert `http.calls ==
  []`, proving no I/O was attempted.
- `Adapter` protocol in `base.py` now carries a docstring documenting exactly
  what `collect.py` relies on: failures raise only `AdapterError`; an empty
  result is `[]`, not an exception; `published_at` is tz-aware UTC or `None`,
  never naive; `since` is advisory, and today's orchestrator always passes
  `None` (cross-referencing F1).

No dedicated "would fail against old code" test was written for the
docstring or the two `-> None` annotation groups (these are not
behavior-affecting; there's nothing for a test to discriminate). The web.py
URL-validation item does have a discriminating test — see verification for
that specific piece.

---

## F12 — real gh binary verification

No code changes; a verification exercise per the plan. Used the **primary**
`reachstore` database (not the test database), which already had the
migrated schema and two pre-existing sources from earlier task work.

```
$ .venv/bin/reachstore add-source github_repo octocat/Hello-World --tier 3
added github_repo octocat/Hello-World (tier 3)
$ echo exit: $?
exit: 0

$ .venv/bin/reachstore collect --tier 3
source 3: failed — AdapterError: gh failed (4): To get started with GitHub CLI, please run:  gh auth login
Alternatively, populate the GH_TOKEN environment variable with a GitHub API authentication token.
1 source(s) processed
$ echo exit: $?
exit: 1

$ .venv/bin/reachstore health
[success] rss https://github.blog/feed/ (failures: 0)
[failed] rss https://this-domain-should-not-resolve-zzzzz1234.invalid/feed (failures: 1)
[failed] github_repo octocat/Hello-World (failures: 1)
```

Direct check of the `fetch_runs` row for the new source:
```
(id=5, source_id=3, status='failed',
 error_text='AdapterError: gh failed (4): To get started with GitHub CLI, please run:  gh auth login\n'
            'Alternatively, populate the GH_TOKEN environment variable with a GitHub API authentication token.')
```

All three required checks confirmed:
- **Clean recorded failure**: `fetch_runs.status = "failed"`, `error_text`
  names the auth problem verbatim (`gh`'s own message), not a leaked
  `CalledProcessError`/traceback. The CLI's own stdout also shows the failure
  as a normal one-line message, no traceback.
- **CLI exits 1**: confirmed (`collect --tier 3` had exactly one source, and
  it failed).
- **health reports it as failing**: `[failed] github_repo octocat/Hello-World
  (failures: 1)`.

Used `octocat/Hello-World` (a real, public, well-known repo) for tier 3, a
tier with no other sources, so the exit-code check is unambiguous (single
source, single failure). `gh auth status` was confirmed non-zero/unauthenticated
before running (`exit: 1`, "You are not logged into any GitHub hosts")
and `gh auth login` was not attempted, per instructions. This exercised the
real `SubprocessRunner` → real `gh` binary → real non-zero exit code → F3's
wrapping → `collect_source`'s bulkhead, end to end.

---

## Full-suite verification history

Ran `.venv/bin/pytest -q` before every commit; it was green every time:

| After | Tests |
|---|---|
| baseline | 64 passed |
| F10 | 67 passed |
| F1 | 68 passed |
| F2 | 70 passed |
| adapter-contract group (F3/F5/F6/F8/F11) | 77 passed |
| query-layer group (F4/F7) | 84 passed |
| F9 | 86 passed |

Final run:
```
.venv/bin/pytest -q
...
86 passed in 1.44s
```

## Things I did not change / disagreed with

Nothing. Every fix's premise held when checked, with the one caveat noted
under F1 (`last_run_started_at` does not become dead code — it's still used
by `should_attempt` for backoff — so I did not add the "leave it, don't
delete" comment the fix description anticipated, since there was nothing to
protect against). No existing test was weakened; the two intentionally
updated tests (F2's pagination fixture, F4's health test) are documented
above with the reasoning, as instructed.

## Files touched (all under /Users/dev2/Desktop/Testing)

- `src/reachstore/collect.py`
- `src/reachstore/query.py`
- `src/reachstore/cli.py`
- `src/reachstore/adapters/base.py`
- `src/reachstore/adapters/rss.py`
- `src/reachstore/adapters/github.py`
- `src/reachstore/adapters/web.py`
- `tests/conftest.py`
- `tests/test_conftest_safety.py` (new)
- `tests/test_collect.py`
- `tests/test_query_isolation.py`
- `tests/test_query_search.py`
- `tests/test_adapter_base.py`
- `tests/test_adapter_github.py`
- `tests/test_adapter_rss.py`
- `tests/test_adapter_web.py`
- `tests/test_cli.py`
- `tests/fixtures/rss_content_encoded.xml` (new)

## Commits (feat/core-store-tier1)

```
c874a5c fix: validate kind and make add-source idempotent (F9)
5791443 fix: remove misleading user_id from source_health and clamp read limits (F4, F7)
87a1fc2 fix: adapter-contract fixes and consistency (F3, F5, F6, F8, F11)
684428a fix: use a compound (published_at, id) keyset cursor in feed() (F2)
28f0b2a fix: stop passing a since watermark to adapters, it drops items permanently (F1)
a1fdfa1 fix: refuse to drop the test schema unless the DB is clearly a test DB (F10)
```
