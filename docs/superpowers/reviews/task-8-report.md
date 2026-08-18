# Task 8 Report: Typer CLI

## What I implemented

Created `src/reachstore/cli.py` — the composition root of the whole system — exactly as specified in the task brief, verbatim. It exposes a Typer app (`reachstore.cli.app`) with four commands:

- `add-source <kind> <identifier> [--tier N]` — registers a `Source` row and commits.
- `collect [--tier N] [--force]` — builds the real adapter registry, calls `collect_tier(..., now=datetime.now(UTC))`, commits, and echoes one line per source (success: `new / found` counts; failure: `failed — <error_text>`), followed by a summary count of sources processed.
- `search <q> --user-id ID [--kind K] [--limit N]` — calls `query.search` and prints each matching item's published date, title, and URL, followed by a result count.
- `health --user-id ID` — calls `query.source_health` and prints a status line per source (`NEEDS ATTENTION`, the last run's status, or `never run`).

Also implemented `build_default_registry() -> dict[str, Adapter]`, which wires the real `HttpxFetcher()` and `SubprocessRunner()` into `adapters.registry.build_registry`. `cli.py` is the only place in the codebase that constructs these, and the only place that reads the real clock.

`_session()` and `_raw_dir()` are plain module-level functions, called at the top of each command body (not captured as decorator arguments or default values), so `monkeypatch.setattr(cli, "_session", ...)` and `monkeypatch.setattr(cli, "_raw_dir", ...)` intercept them at call time as the tests require. Same pattern for `build_default_registry`.

Created `tests/test_cli.py` with the two tests specified in the brief, copied verbatim:
- `test_add_source_then_collect_then_search` — exercises the full `add-source` → `collect` → `search` flow with a stub RSS adapter, asserting the source row, item row, and search output all reflect what was collected.
- `test_collect_reports_failures_without_crashing` — exercises a broken adapter raising `RuntimeError("upstream exploded")`, asserting `collect` exits 0 and surfaces both `"failed"` and the underlying error text in stdout.

## TDD Evidence

### RED

Command: `.venv/bin/pytest tests/test_cli.py -v`

Output (before `src/reachstore/cli.py` existed):

```
==================================== ERRORS ====================================
______________________ ERROR collecting tests/test_cli.py ______________________
ImportError while importing test module '/Users/dev2/Desktop/Testing/tests/test_cli.py'.
...
tests/test_cli.py:5: in <module>
    from reachstore import cli
E   ImportError: cannot import name 'cli' from 'reachstore' (/Users/dev2/Desktop/Testing/src/reachstore/__init__.py)
=========================== short test summary info ============================
ERROR tests/test_cli.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
=============================== 1 error in 0.09s ===============================
```

This is expected: `reachstore.cli` did not exist yet. The brief predicted `ModuleNotFoundError: No module named 'reachstore.cli'`; the actual message is `ImportError: cannot import name 'cli' from 'reachstore'` because the test does `from reachstore import cli` (attribute-style import) rather than `import reachstore.cli` — same root cause (the submodule doesn't exist), different Python import-machinery wording. Confirms the test genuinely fails for the right reason before implementation exists.

### GREEN

Command: `.venv/bin/pytest tests/test_cli.py -v`

Output (after implementing `src/reachstore/cli.py`):

```
tests/test_cli.py::test_add_source_then_collect_then_search PASSED       [ 50%]
tests/test_cli.py::test_collect_reports_failures_without_crashing PASSED [100%]

============================== 2 passed in 0.20s ===============================
```

## Full-suite result before committing

Command: `.venv/bin/pytest`

```
============================== 62 passed in 0.32s ===============================
```

62/62 — the 60 pre-existing tests from Tasks 1-7 plus the 2 new CLI tests, all green, no warnings, no network access performed by the suite (the stub/broken adapters in `test_cli.py` never touch `httpx` or `subprocess`).

Re-ran once more after the commit as a final sanity check: still `62 passed in 0.39s`.

## Files changed

- `src/reachstore/cli.py` (new) — the CLI composition root.
- `tests/test_cli.py` (new) — the two brief-specified tests.

No earlier task's code was modified.

## Codebase-wide `datetime.now` grep

```
$ grep -rn "datetime.now" src/
src/reachstore/cli.py:46:            created_at=datetime.now(UTC),
src/reachstore/cli.py:62:        now=datetime.now(UTC),
```

Both occurrences are in `cli.py` (one in `add_source`, one in `collect`, passed down as the `now=` keyword to `collect_tier`). No occurrences anywhere else in `src/`. Also grepped for `utcnow` across `src/` — zero hits, so no naive-datetime construction anywhere.

## Reasoning on exit-code behavior

I followed the brief's reference implementation verbatim: every command returns `None` on completion and Typer's default behavior yields exit code 0 whenever no exception propagates, including when `collect` reports one or more failed sources. I considered whether `collect` should return a non-zero exit code when any source fails (useful for a script wrapping this CLI in a cron job to detect partial failure), but the brief's own test, `test_collect_reports_failures_without_crashing`, explicitly asserts `result.exit_code == 0` even when a source fails with `"upstream exploded"`. Since the brief is unusually prescriptive here — it hands over literal implementation code and a test that pins this exact behavior — I did not deviate. The system already has a "never crash the whole run over one bad source" bulkhead in `collect_tier`/`collect_source`; a non-zero process exit on partial failure would be a legitimate design choice for a future iteration, but changing it here would contradict the brief's own test and go beyond what was asked. Uncaught, unexpected exceptions (e.g., an unreachable database) still propagate and Typer/Click convert them into a non-zero exit code with a traceback, which is the correct behavior for "the CLI itself is broken" as opposed to "one upstream source is broken."

## Self-review findings

- **Completeness:** All four commands present — confirmed via `.venv/bin/reachstore --help` listing `add-source`, `collect`, `search`, `health`.
- **Clock discipline:** Verified via `grep -rn "datetime.now" src/` — only the two calls inside `cli.py`. No `utcnow` anywhere.
- **No SQL:** `cli.py` imports only `sqlalchemy.orm.Session` (a type hint, not query construction) and never imports `select`. No query-building in the module — confirmed by reading the file end to end.
- **Option vs argument:** Verified with `.venv/bin/reachstore search --help` and `.venv/bin/reachstore health --help` — `--user-id` appears under `Options` as a required flag (`*  --user-id  <int>  [required]`) in both commands, not as a positional argument.
- **Monkeypatch compatibility:** `_session`, `_raw_dir`, and `build_default_registry` are module-level functions called fresh inside each command body at invocation time — not bound at decoration time, not evaluated as default-argument expressions. `monkeypatch.setattr(cli, "_session", lambda: session)` therefore intercepts correctly, proven by both tests passing against the real Postgres test fixture session.
- **Honest reporting:** `collect` echoes a per-source line for every result, distinguishing `failed — <error_text>` from `<new> new / <found> found` for successes, then a summary count — it never claims a blanket success. Verified by `test_collect_reports_failures_without_crashing` asserting both `"failed"` and `"upstream exploded"` appear in stdout.
- **Quality and discipline:** Implementation matches the brief exactly — no extra subcommands, no config commands, no interactive prompts, no progress bars, no added color. File is 100 lines, proportionate to four thin CLI commands wired to already-tested lower layers.
- **Testing:** `62 passed in 0.32s` (and again `0.39s` post-commit), no warnings, no deprecation notices, no stray output.

No issues found requiring fixes.

## Hand verification (brief Step 6, network-touching, outside the automated suite)

Network access and the `reachstore` dev Postgres database (distinct from `reachstore_test`) were both available in this environment, so I ran the brief's manual verification exactly as specified:

```
$ .venv/bin/reachstore add-source rss https://github.blog/feed/ --tier 1
added rss https://github.blog/feed/ (tier 1)

$ .venv/bin/reachstore collect --tier 1
source 1: 10 new / 10 found
1 source(s) processed

$ .venv/bin/reachstore collect --tier 1     # re-run: confirms idempotency
source 1: 0 new / 0 found
1 source(s) processed

$ .venv/bin/reachstore search github --user-id 1 --limit 3
2026-08-14 16:00:00+00:00  How to bring your software delivery workflow into GitHub with agent apps
    https://github.blog/ai-and-ml/github-copilot/how-to-bring-your-software-delivery-workflow-into-github-with-agent-apps/
... (3 results total)
3 result(s)

$ .venv/bin/reachstore health --user-id 1
[success] rss https://github.blog/feed/ (failures: 0)
```

(The `--user-id 1` row was a throwaway `User` I inserted directly into the dev DB via a one-off script, since user creation is out of scope for this CLI per the brief's "What this plan does not cover" — auth/user management is Plan 2.)

This confirms: real RSS collection works end-to-end against the dev database, re-running `collect` immediately produces zero new items (the DoD's idempotency requirement), and `search`/`health` both work against real data.

**Not verified**: the GitHub adapter against a real repository. The `gh` CLI binary is not installed in this sandboxed environment (`gh: command not found`), so `SubprocessRunner` has no upstream binary to invoke for a live check. This is an environment limitation, not a defect in the CLI wiring — `build_default_registry()` wires `SubprocessRunner()` into the registry exactly as the RSS/web adapters are wired to `HttpxFetcher()`, and the GitHub adapter itself was already fully unit-tested against a fake `CommandRunner` in Task 4 (`tests/test_adapter_github.py`, all passing). I'm flagging this gap explicitly rather than silently skipping it.

## Deviations from the brief

None. Implementation, test file, and commit message all match the brief verbatim.

---

## Fix Report: `collect` exit-code rule (post-review)

### What changed

Coordinator review flagged that `collect` always exited 0, even when every source in a tier failed — no signal a wrapper script (e.g. a nightly cron job) could use to distinguish "collected everything fine" from "the whole run failed, go look." Ruling handed down:

- Zero sources in the tier → exit 0 (nothing to do is not a failure).
- Some succeeded, some failed → exit 0 (the bulkhead is working as designed; the circuit breaker already isolates a persistently broken source).
- At least one source, and every one of them failed → exit 1 (systemic problem — DB down, network out, expired credentials — a human should look).

**`src/reachstore/cli.py`** — `collect` command:
- Expanded the docstring (which Typer surfaces as `--help` text) to document the exit-code contract, per the review's instruction that it be discoverable by someone writing a wrapper script.
- Added, after the existing per-source echo loop and summary line (unchanged — every case still prints the same output as before):
  ```python
  if results and all(result.status == "failed" for result in results):
      raise typer.Exit(code=1)
  ```
  Used `typer.Exit(code=1)`, not `sys.exit`, as instructed. `results` is empty when the tier has no sources or every source in it is deferred by backoff, so the `results and ...` guard correctly keeps that case at exit 0.

**`tests/test_cli.py`**:
1. `test_collect_reports_failures_without_crashing` — its one source fails, so under the new rule the tier is 100% failed. Changed the assertion from `result.exit_code == 0` to `result.exit_code == 1`. Left every other assertion (the `"failed"` and `"upstream exploded"` substrings in stdout) untouched — the test's intent (the command reports the failure honestly rather than crashing) is unchanged.
2. Added `test_collect_exits_zero_when_some_sources_succeed` — two sources in tier 1, different kinds (`rss` via the existing `StubAdapter`, and a new `atom`-kind `BrokenAdapter` that raises `RuntimeError("upstream exploded")`), both wired into the registry monkeypatch. Asserts `exit_code == 0` and that both the failure line (`"failed"`) and the success line (`"1 new"`) appear in stdout — this is the test that would catch an over-eager "any failure exits 1" implementation.
3. Added `test_health_lists_source_status` — the only one of the four commands with no prior `CliRunner` exercise. Seeds one `Source`, monkeypatches only `cli._session` (health touches neither the registry nor `raw_dir`), invokes `health --user-id 1`, and asserts `exit_code == 0` and that the seeded source's identifier (`"https://a/feed"`) appears in stdout. `source_health` in `query.py` takes `user_id` but does not filter by it (tenant isolation lives solely in `visible_to`, per the codebase's stated design), so no real `User` row was needed for this test — confirmed by reading `query.source_health`'s body before writing the test.

No Task 1-7 code was touched. No other file was modified.

### Covering tests

Command: `.venv/bin/pytest tests/test_cli.py -v`

```
tests/test_cli.py::test_add_source_then_collect_then_search PASSED       [ 25%]
tests/test_cli.py::test_collect_reports_failures_without_crashing PASSED [ 50%]
tests/test_cli.py::test_collect_exits_zero_when_some_sources_succeed PASSED [ 75%]
tests/test_cli.py::test_health_lists_source_status PASSED                [100%]

============================== 4 passed in 0.22s ===============================
```

Note on count: `tests/test_cli.py` now holds **4** tests (the original 2 from the brief, one of them amended, plus the 2 newly added), not 5 as stated in the review's Verify step 1. The review's own full-suite expectation of 64/64 is internally consistent with 4 (60 pre-existing + 4 in this file = 64), so I believe "5 tests" in that step was a simple miscount rather than an instruction to add a further test; I did not fabricate a fifth test to force that number, and I'm flagging the discrepancy explicitly rather than silently reconciling it.

Command: `.venv/bin/pytest`

```
============================== 64 passed in 0.37s ===============================
```

64/64, matching the review's expected full-suite count (60 from Tasks 1-7 + 4 in `test_cli.py`), no warnings, pristine output.

### Hand-verified real-process exit code (not just `CliRunner`)

Per the review's request, I exercised the all-failed case as an actual OS process against the dev database (`reachstore`, not `reachstore_test`), isolated in tier 2 so it wouldn't collide with the tier-1 source from the original Step 6 hand verification:

```
$ .venv/bin/reachstore add-source rss "https://this-domain-should-not-resolve-zzzzz1234.invalid/feed" --tier 2
added rss https://this-domain-should-not-resolve-zzzzz1234.invalid/feed (tier 2)

$ .venv/bin/reachstore collect --tier 2; echo "EXIT CODE: $?"
source 2: failed — AdapterError: HTTP request failed for https://this-domain-should-not-resolve-zzzzz1234.invalid/feed: [Errno 8] nodename nor servname provided, or not known
1 source(s) processed
EXIT CODE: 1
```

And confirmed the mixed/success path still exits 0 in a real process too (tier 1, which holds the already-successful `github.blog` source from the original hand verification):

```
$ .venv/bin/reachstore collect --tier 1; echo "EXIT CODE: $?"
source 1: 0 new / 0 found
1 source(s) processed
EXIT CODE: 0
```

Both match the ruling: all-failed real tier → real process exit 1; a tier containing at least one success → real process exit 0.

### Commit

`4fcdbd1` — "fix: exit 1 from collect when every source in a tier fails" (`src/reachstore/cli.py`, `tests/test_cli.py`).
