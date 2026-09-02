# Task 9 report: Playwright smoke test

## What I implemented

Followed `task-9-brief.md` verbatim, with one disclosed deviation (see Concerns).

- `web/tests/seed_e2e.py` — seeds 1 source + 12 items into the test database, guarded by the
  `_test` suffix check, idempotent via `upsert_items`'s `on_conflict_do_nothing`. Copied verbatim
  from the brief.
- `web/playwright.config.js` — reads `../.env` for `TEST_DATABASE_URL`, passes it as `DATABASE_URL`
  to the API server subprocess, starts both the API (`reachstore.api.app.serve`, port 8000,
  `reuseExistingServer: false`) and the Vite dev server (port 5173, `reuseExistingServer: true`).
  Copied verbatim from the brief.
- `web/tests/smoke.spec.js` — 3 tests: feed listing + detail pane, search + clear, health strip
  expand. Copied verbatim from the brief.
- `web/package.json` — added `seed:e2e` and `test:e2e` scripts, exactly as specified.
- `web/.gitignore` — added `test-results` and `playwright-report` (Playwright creates these; they
  were not previously ignored).

## Deviation from the brief: Playwright version pin

`npm install -D @playwright/test` (unpinned) installed the latest release, 1.62.1, whose
`playwright-core` expects Chromium revision **1234**. The cache on this machine
(`~/Library/Caches/ms-playwright`) only holds revision **1228** (`chromium-1228` and
`chromium_headless_shell-1228`), so the first `npm run test:e2e` run failed all 3 tests with:

```
Error: browserType.launch: Executable doesn't exist at
/Users/dev2/Library/Caches/ms-playwright/chromium_headless_shell-1234/...
```

The brief said browsers were already cached and forbade `npx playwright install`. Rather than
running that (which the brief explicitly ruled out) or killing/reconfiguring anything, I checked
npm's registry for the `playwright-core` release whose `browsers.json` pins revision 1228, found
`1.61.1` (the latest patch on the 1.61.x line), and installed that exact version instead:

```bash
npm install -D @playwright/test@1.61.1
```

This is a genuine environment fact worth flagging: "browsers are cached" was true, but it only
holds for a `@playwright/test` version whose expected revision matches what's on disk (1228), not
for whatever is currently latest on npm. `web/package.json` now reads
`"@playwright/test": "^1.61.1"` and `web/package-lock.json` pins the exact resolved version, so a
fresh `npm ci` reproduces this working combination. I did not touch anything else to work around
this — no browser install, no port changes, no assertion weakening.

## Seed idempotency — two runs proving it (Step 3)

First run (fresh, after Step 2):
```
$ .venv/bin/python web/tests/seed_e2e.py
seeded 12 items (12 new) into reachstore_test
```

Second run, immediately after:
```
$ .venv/bin/python web/tests/seed_e2e.py
seeded 12 items (0 new) into reachstore_test
```

12 new, then 0 new — idempotency confirmed as specified.

(Later, after running the Python test suite — whose `engine` fixture does `DROP SCHEMA` on this
same test database at session scope, exactly as the seed script's own docstring warns — I reseeded
and saw `12 new` again on the first post-drop run, then `0 new` on the run after that. That is the
documented, expected interaction, not a bug: the schema was gone, so the source/items had to be
recreated, and idempotency held again once the data was back.)

## Full `npm run test:e2e` output (final clean run)

```
> web@0.0.0 test:e2e
> npm run seed:e2e && playwright test

> web@0.0.0 seed:e2e
> cd .. && .venv/bin/python web/tests/seed_e2e.py

seeded 12 items (0 new) into reachstore_test
[WebServer] INFO:     Started server process [1692]
[WebServer] INFO:     Waiting for application startup.
[WebServer] INFO:     Application startup complete.
[WebServer] INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)

Running 3 tests using 1 worker

  ✓  1 tests/smoke.spec.js:3:1 › the feed lists items and clicking one opens its full text (188ms)
  ✓  2 tests/smoke.spec.js:21:1 › searching narrows the list and clearing restores it (212ms)
  ✓  3 tests/smoke.spec.js:41:1 › the health strip expands to show per-source detail (147ms)

  3 passed (2.0s)
```

3 passed, as expected. I ran the full suite three times total during this task (once with the
version mismatch — 3 failed — then twice successfully after pinning 1.61.1); the output above is
from the final run before committing.

## Python suite confirmation

Ran `.venv/bin/pytest` from the repo root after the e2e work:

```
============================= 116 passed in 1.70s ==============================
```

116 passed, no warnings printed in the summary — matches the "116 tests, zero warnings" baseline
stated in the task context. I did not modify anything under `src/` or `tests/` (Python).

## Files changed

- `web/tests/seed_e2e.py` (new)
- `web/playwright.config.js` (new)
- `web/tests/smoke.spec.js` (new)
- `web/package.json` (modified — added scripts + `@playwright/test` devDependency)
- `web/package-lock.json` (modified — committed, pins `@playwright/test@1.61.1` and its
  transitive deps)
- `web/.gitignore` (modified — added `test-results`, `playwright-report`)

Commit: `fd70564` — "test: hermetic Playwright smoke test against the seeded test database"

## Self-review findings

- **Completeness:** all four required files present, both npm scripts added, `package-lock.json`
  staged and committed (verified with the brief's own `git status --short web | grep
  package-lock.json` check before committing).
- **Honesty:** every number in this report (12/12 new, 12/0 new, 3 passed, 116 passed) is copied
  directly from a command I ran during this session, not inferred. The one deviation (Playwright
  version pin) is disclosed above with the exact error and the exact fix, not smoothed over.
- **Determinism:** the seed script guards on `_test` suffix, migrates via Alembic, and upserts
  fixed data; `test:e2e` always seeds before testing. A fresh clone with `npm ci` would resolve
  `@playwright/test@1.61.1` from the lock file — matching the cached browser revision on this
  machine — and `npm run test:e2e` would behave identically. (On a *different* machine without
  revision-1228 browsers cached, a real `npx playwright install` would still be needed; that's
  outside what a lock file can guarantee, but is a pre-existing constraint of Playwright, not
  something this task introduced.)
- **Cleanliness:** working tree is clean after commit (`git status --short` empty). Ports 8000 and
  5173 confirmed free before and after every run — the webServer processes shut down on their own
  when Playwright's test runner exited each time; I never had to kill anything. A stray
  `web/test-results/` directory left over from the one failed run (before the version pin) was
  deleted before committing and is now `.gitignore`d.

## Concerns

- The one deviation from the brief's literal instructions is the Playwright version pin
  (`1.61.1` instead of whatever `npm install -D @playwright/test` resolves to unpinned). I did not
  run `npx playwright install`, did not touch ports, and did not weaken any assertion — this was
  the only path that used only what was already cached, as instructed. Flagging it explicitly per
  the task's request to report rather than paper over environment mismatches.
- No other concerns. All three tests pass against exact, seeded counts with no relaxed assertions.

---

## Fix report (post-review)

Reviewer approved the original implementation and found two Important issues. Both fixed.

### Finding 1: undocumented Playwright version pin

- Added a comment block at the top of `web/playwright.config.js` explaining that
  `@playwright/test` is pinned to 1.61.1 (not left as a floating caret) because that's the newest
  release whose `playwright-core` expects the Chromium revision (1228) already cached on this
  machine, and that bumping the version requires either `npx playwright install chromium` or
  confirming the new target revision is already cached.
- Added an "End-to-end test" section to `web/README.md` covering: what `npm run test:e2e` does,
  that port 8000 must be free, that it's deterministic (seeds exact data), and the exact recovery
  command (`npx playwright install chromium`) for the `Executable doesn't exist` failure mode,
  pointing back at the config comment for why the version is held where it is.

### Finding 2: seed script's guard comment overstated coverage

`web/tests/seed_e2e.py` implemented only the suffix check (`_test`), not conftest.py's second
guard (URL must differ from the primary `DATABASE_URL`). Added the missing check verbatim as
specified:

```python
    if url == settings.database_url:
        raise SystemExit("TEST_DATABASE_URL must differ from DATABASE_URL. Refusing to seed.")
```

placed after the existing suffix check, and updated the comment to say it implements both of
conftest's guards.

### Guard verification (both checks proven independently, `.env` untouched)

Test A — the literal repro suggested (set `TEST_DATABASE_URL` to the real `DATABASE_URL` value in
a subshell). This actually trips guard 1 (suffix), not guard 2, because the real dev database name
doesn't end in `_test`:

```
$ ( DB_URL=$(grep '^DATABASE_URL=' .env | cut -d= -f2-); TEST_DATABASE_URL="$DB_URL" .venv/bin/python web/tests/seed_e2e.py; echo "exit code: $?" )
TEST_DATABASE_URL must be set and end in '_test'. Refusing to seed.
exit code: 1
```

Test B — isolating guard 2 specifically: override both `DATABASE_URL` and `TEST_DATABASE_URL` in
the subshell to an identical fabricated value that *does* end in `_test`, so guard 1 passes and
only guard 2 can catch it:

```
$ ( FAKE_URL="postgresql://x/reachstore_test"; DATABASE_URL="$FAKE_URL" TEST_DATABASE_URL="$FAKE_URL" .venv/bin/python web/tests/seed_e2e.py; echo "exit code: $?" )
TEST_DATABASE_URL must differ from DATABASE_URL. Refusing to seed.
exit code: 1
```

Guard 2 fires correctly and in isolation. `.env` was never read into an editor or modified in
either test — only a shell variable was extracted from it via `grep`/`cut` for Test A, and Test B
used a fabricated string with no real credentials at all.

### Re-run after the fixes

```
> web@0.0.0 test:e2e
> npm run seed:e2e && playwright test

> web@0.0.0 seed:e2e
> cd .. && .venv/bin/python web/tests/seed_e2e.py

seeded 12 items (0 new) into reachstore_test
[WebServer] INFO:     Started server process [3067]
[WebServer] INFO:     Waiting for application startup.
[WebServer] INFO:     Application startup complete.
[WebServer] INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)

Running 3 tests using 1 worker

  ✓  1 tests/smoke.spec.js:3:1 › the feed lists items and clicking one opens its full text (307ms)
  ✓  2 tests/smoke.spec.js:21:1 › searching narrows the list and clearing restores it (209ms)
  ✓  3 tests/smoke.spec.js:41:1 › the health strip expands to show per-source detail (125ms)

  3 passed (2.2s)
```

3 passed, confirmed again.

### Files changed (this fix round)

- `web/README.md` (modified — new "End-to-end test" section)
- `web/playwright.config.js` (modified — version-pin rationale comment)
- `web/tests/seed_e2e.py` (modified — added the missing `DATABASE_URL` equality guard, corrected
  comment)

Commit: `97f4cde` — "fix: document e2e Playwright version pin and add missing DB-equality guard"

### Note on an unrelated working-tree file

`docs/superpowers/plans/2026-09-02-web-ui-and-api.md` was modified in the working tree (the
coordinator's own correction to the plan, per their message: "I have already corrected the plan").
That file is outside this task's scope (`web/` only per the brief), so I left it untouched and did
not stage or commit it — it remains as the coordinator's own pending edit.

### Cleanliness

Ports 8000 and 5173 confirmed free before and after this round; no process was killed. A stray
`web/test-results/` directory reappeared after this round's `npm run test:e2e` run (Playwright
appears to create it even on an all-passing run) and was deleted before finishing — it's
`.gitignore`d from the original commit, so it was never at risk of being committed.

### Concerns

None outstanding. Both Important findings are fixed and verified; the one deferred Minor
(`.env` parsing not stripping quotes) was explicitly out of scope for this round.
