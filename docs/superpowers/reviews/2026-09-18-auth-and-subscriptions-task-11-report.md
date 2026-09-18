# Task 11: End-to-end tests — Report

## Status: DONE

## What was implemented

Followed the brief's six steps in order.

1. **`web/tests/seed_e2e.py`** — added `E2E_EMAIL`/`E2E_PASSWORD` constants, a
   check-then-create block seeding an admin `User` (idempotent, matching the
   existing `Source` pattern), and extended the final print. **One addition
   beyond the brief's literal text**: after creating/finding the user, the
   script now resets that user's subscriptions to `active=False`:

   ```python
   session.execute(
       update(Subscription).where(Subscription.user_id == user.id).values(active=False)
   )
   ```

   Reason: `store.subscribe()`/`unsubscribe()` never delete a `Subscription`
   row, only flip `active` (confirmed in `src/reachstore/store.py`). The new
   `auth.spec.js` subscription test asserts "nothing subscribed" as its
   starting state. Without this reset, running `npm run test:e2e` a second
   time in a row — a completely ordinary thing to do — would leave that
   precondition false and the test would fail on the second run. The file's
   own docstring already promises it is "Safe to run before every e2e
   invocation"; this change makes that literally true for subscriptions too.
   I verified this empirically (see "Repeatability" below) before adding it.

2. **`web/tests/smoke.spec.js`** — added the `signIn()` helper exactly as
   specified and replaced all four `page.goto('/')` calls with `signIn(page)`.
   The `javascript:` URL test keeps `page.route(...)` registered before
   `signIn(page)`, per the brief's ordering requirement.

3. **`web/tests/auth.spec.js`** — created with all 8 tests from the brief,
   with one deviation in the last test (see below).

4. **`web/playwright.config.js`** — added the readiness-probe comment. I
   worded it to record what I actually verified, not just what was predicted:
   the suite does not hang on the `/api/sources` 401 probe (confirmed across
   three full runs). No switch to `/api/docs` was needed.

5. Ran the suite — see full output below.

6. Committed (`b8eba45`).

## Deviation from the brief, with evidence: the subscription test's `.check()`

The brief's `auth.spec.js` code for the last test used:

```js
await page.locator('.subs-list input[type="checkbox"]').first().check()
```

This failed deterministically on the first real run:

```
Error: locator.check: Clicking the checkbox did not change its state
```

I did not assume this was a flake. I isolated it with a throwaway debug spec
(deleted afterward, not committed) that sampled `checkbox.isChecked()` at
increasing delays after a raw `.click()`:

```
BEFORE: false
+0ms   checked= false
+1ms   checked= false
+5ms   checked= false
+20ms  checked= true
+50ms  checked= true
```

Root cause: `SubscriptionStrip.jsx`'s checkbox is `checked={e.subscribed}`,
and `e.subscribed` only becomes `true` after `toggle()` awaits the
`PUT /api/subscriptions/{id}` round-trip and a subsequent `fetchCatalog()`
reload — roughly a 15–20ms async gap on localhost. Playwright's `.check()`
performs the click and then asserts the new `checked` state **immediately,
with no retry**. It loses this race every time, even though the click and
the underlying subscribe both succeed a few milliseconds later (confirmed:
the subscription was persisted to the database after the "failed" test
completed).

This is a test-authoring/API mismatch, not an app bug — the app's checkbox
correctly reflects server-confirmed state rather than optimistically
flipping before the request is known to have succeeded. The fix belongs in
the test. I changed only this:

```js
const checkbox = page.locator('.subs-list input[type="checkbox"]').first()
await checkbox.click()
await expect(checkbox).toBeChecked()   // polls, unlike check()'s one-shot assertion
```

Everything else in `auth.spec.js` is verbatim from the brief. I'm flagging
this per the standing instruction to say so with evidence rather than
silently following a brief I believe is wrong — this one is a very small,
well-precedented case (a Playwright API footgun with async-controlled
inputs), not a design disagreement.

## Full e2e run output (12 passing)

Run with the temporary port override in place (see "Ports" below):

```
> web@0.0.0 test:e2e
> npm run seed:e2e && playwright test

> web@0.0.0 seed:e2e
> cd .. && .venv/bin/python web/tests/seed_e2e.py

seeded 12 items (0 new) and admin e2e-admin@example.test into reachstore_test
Uvicorn running on http://127.0.0.1:8100 (Press CTRL+C to quit)

Running 12 tests using 2 workers

  ✓  2 tests/auth.spec.js:6:1 › an anonymous visit shows the login form, not the feed (343ms)
  ✓  1 tests/smoke.spec.js:17:1 › the feed lists items and clicking one opens its full text (575ms)
  ✓  3 tests/auth.spec.js:12:1 › a wrong password is rejected with one generic message (251ms)
  ✓  5 tests/auth.spec.js:22:1 › an unknown email gives the same message as a wrong password (225ms)
  ✓  4 tests/smoke.spec.js:37:1 › an item with a javascript: URL renders its title as plain text, not a link (313ms)
  ✓  6 tests/auth.spec.js:31:1 › signing in and out round-trips (274ms)
  ✓  7 tests/smoke.spec.js:65:1 › searching narrows the list and clearing restores it (304ms)
  ✓  8 tests/auth.spec.js:45:1 › the session survives a reload without a login flash (285ms)
  ✓  9 tests/smoke.spec.js:85:1 › the health strip expands to show per-source detail (279ms)
  ✓ 10 tests/auth.spec.js:57:1 › an invalid setup token is reported, not silently accepted (174ms)
  ✓ 11 tests/auth.spec.js:68:1 › mismatched setup passwords are caught before the request (156ms)
  ✓ 12 tests/auth.spec.js:78:1 › subscribing from the strip filters a subscribed-only search (427ms)

  12 passed (3.7s)
```

### Repeatability (proves the subscription reset works)

Ran `npm run test:e2e` a second time immediately after, with no manual
cleanup in between — this is exactly the scenario the seed's subscription
reset fixes:

```
seeded 12 items (0 new) and admin e2e-admin@example.test into reachstore_test
Running 12 tests using 2 workers
  ✓ ... (all 12, same as above)
  12 passed (3.4s)
```

### Also verified

- `.venv/bin/python -m pytest -q` after the e2e runs: **202 passed** — Python
  suite untouched, no regression. (Run only after e2e had fully finished —
  never concurrently, per the standing warning about the `engine` fixture's
  `DROP SCHEMA`.)
- `cd web && npm run build`: succeeds (`vite build`, 25 modules, no errors)
  — this project's build gate.
- A final `npm run test:e2e` run **after reverting the config back to
  8000/5173** was attempted deliberately, to prove the reverted config is
  the real, unmodified one: it correctly failed with
  `[Errno 48] address already in use` against PHP's port 8000, and exited
  cleanly (code 3) without touching PHP. This is expected — 8000 is occupied
  on this machine — and is not a suite failure; it's proof the committed
  config is genuinely reverted rather than quietly still pointing at 8100.

## Ports actually run on, and proof the config is reverted

- Checked before starting: `lsof -nP -iTCP:8000/8001/5173/8100/5273 -sTCP:LISTEN`
  showed PHP (PID 29601) on 8000, PHP (PID 53638) on 8001, and 5173/8100/5273
  all free.
- Since **5173 was free**, only the API port needed an override. I ran the
  suite on **API port 8100**, Vite stayed on its default **5173** (no
  `vite.config.js` port change needed, but its `/api` proxy target had to
  temporarily point at 8100 to match).
- Temporary edits during the run:
  - `web/playwright.config.js`: `serve()` → `serve(port=8100)`, probe URL →
    `http://127.0.0.1:8100/api/sources`.
  - `web/vite.config.js`: proxy target → `http://127.0.0.1:8100`.
- Reverted before committing:
  - `web/vite.config.js`: `git checkout -- web/vite.config.js` (this file has
    no other changes, so a full checkout is exact).
  - `web/playwright.config.js`: manually edited the port/URL back to
    8000/`serve()` while **keeping** the Step 4 readiness-probe comment
    (a full `git checkout` would have discarded that intentional addition
    too).

Proof, taken after reverting and before committing:

```
$ git diff web/vite.config.js
(empty)

$ git diff web/playwright.config.js
+      // Returns 401 now that every endpoint requires a session. Playwright
+      // treats 401/403 as "the server is up", which is the only thing this
+      // probe needs to establish. Verified: the suite does not hang waiting
+      // on this webServer entry.
(command and url lines unchanged: serve(), http://127.0.0.1:8000/api/sources)

$ grep -rn "8100" web/
(no output)

$ grep -rn "8100" .   # repo-wide
docs/superpowers/plans/2026-09-18-auth-and-subscriptions.md:2175: ... (pre-existing, untouched historical plan doc)
docs/superpowers/plans/2026-09-18-auth-and-subscriptions.md:3598: ... (same)
```

Both hits are pre-existing lines in the preserved plan document (never
touched by me); nothing under `web/` or anywhere else references 8100.

Final committed diff on `playwright.config.js` (only the intended comment):

```diff
--- a/web/playwright.config.js
+++ b/web/playwright.config.js
@@ -38,6 +38,10 @@ export default defineConfig({
     {
       command: 'cd .. && .venv/bin/python -c "from reachstore.api.app import serve; serve()"',
       url: 'http://127.0.0.1:8000/api/sources',
+      // Returns 401 now that every endpoint requires a session. Playwright
+      // treats 401/403 as "the server is up", which is the only thing this
+      // probe needs to establish. Verified: the suite does not hang waiting
+      // on this webServer entry.
       env: { DATABASE_URL: TEST_DB },
       reuseExistingServer: false,
       timeout: 30000,
```

## The 401 readiness probe — what I found

Verified, not assumed: across three full `npm run test:e2e` runs on port
8100, the webServer step consistently reported "Uvicorn running on
http://127.0.0.1:8100" and Playwright proceeded straight into the test run
— no hang, no timeout. `GET /api/sources` unauthenticated does return 401
(confirmed by reading `require_admin`/`get_current_user` in
`src/reachstore/api/auth.py`: no token → 401; the alternate 403 path is for
a non-admin session). Playwright's own webServer readiness check treats any
of 2xx/3xx/401/403 as "up." No change to `/api/docs` was necessary. The
comment added to `playwright.config.js` records this as verified rather than
merely documented-behavior.

## PHP processes — before and after

Before starting:
```
php  29601  ... 08-09:08:51  -S 127.0.0.1:8000 ... mdpos8 ... (Laravel dev server)
php  53638  ... 10-03:56:30  -S 127.0.0.1:8001 ... mdpos8 ...
```

After all work (multiple e2e runs, a pytest run, and a final deliberate
bind-collision run against the reverted 8000 config):
```
php  29601  ... 08-09:17:07  -S 127.0.0.1:8000 ... mdpos8 ...   (still up, uptime increased, never restarted)
php  53638  ... 10-03:57:34  -S 127.0.0.1:8001 ... mdpos8 ...   (still up)
```

Both PIDs identical before and after, `lsof` confirms both still LISTENing
on their original ports. Neither was ever sent a signal. The one deliberate
attempt to run against port 8000 (to prove the config was truly reverted)
failed to bind with `[Errno 48] address already in use` and exited cleanly
— it never touched PHP's socket.

## Files changed

- `/Users/dev2/Desktop/Testing/web/tests/seed_e2e.py` (modified)
- `/Users/dev2/Desktop/Testing/web/tests/smoke.spec.js` (modified)
- `/Users/dev2/Desktop/Testing/web/tests/auth.spec.js` (created)
- `/Users/dev2/Desktop/Testing/web/playwright.config.js` (modified, comment only)
- `/Users/dev2/Desktop/Testing/web/vite.config.js` — touched temporarily, fully reverted, **not** in the commit

Commit: `b8eba45` — "test: e2e coverage for login, setup, and subscriptions"

## Self-review findings

- **Completeness**: seed updated (admin + subscription reset), all 4 smoke
  tests sign in via the shared helper, all 8 new auth tests present, probe
  verified empirically. 12/12 pass, twice in a row.
- **Quality**: the one deviation (`.check()` → `.click()` +
  `toBeChecked()`) is minimal, scoped to the single broken assertion,
  documented inline in the test and here, and does not weaken what the test
  proves — it still requires the subscribe to actually take effect before
  the search re-runs.
- **Discipline**: `@playwright/test` version untouched (still `1.61.1` in
  `package.json`, unchanged in this diff); `npx playwright install` never
  run; both PHP PIDs alive throughout with unchanged listen ports; config
  reverted and verified via diff + grep, not just claimed.
- **Scope check**: `git diff --stat` on the commit touches exactly the four
  files the brief names (three modified + one created), nothing under
  `docs/superpowers/{specs,plans,reviews}/` touched, `.env` untouched and
  still untracked.

## Concerns

- The subscription-reset addition to `seed_e2e.py` goes slightly beyond the
  brief's literal text. I judged it in-scope because it fixes a real,
  easily-triggered repeatability bug in the exact test the brief specifies,
  using the same idempotency pattern already established in that file, and
  I verified the failure mode empirically before adding the fix. Flagging
  for reviewer attention as the one place I extended beyond the given code.
- The `.check()` → `.click()`/`toBeChecked()` substitution is the other
  deviation, also flagged above with reproduction evidence.
- No other concerns. Both `php` processes are exactly as found. Committed
  config is bit-for-bit the brief's intended 8000/5173, plus the requested
  comment.
