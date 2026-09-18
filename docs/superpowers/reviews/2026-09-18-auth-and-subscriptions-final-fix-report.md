# Final fix wave — report

Branch `feat/auth-and-subscriptions`, from `03258dc`.
Commits created:

- `3c561b8` fix: keep routes.py query-free, normalise emails, and route 401s consistently
- `b1eb3e1` docs+test: security posture, true ownership claims, and setup-flow e2e coverage

All eight fixes landed. Nothing declined.

---

## I1 — `routes.py` built a query

`src/reachstore/api/routes.py:197` called `session.get(Source, source_id)`, which
made the "routes.py builds no queries" invariant false at the exact moment
`docs/architecture.md` §3 documented it as enforced.

Added `query.get_source_by_id(session, source_id) -> Source | None` in
`src/reachstore/query.py`, immediately after `get_source`, and called it from
`put_subscription`. The body is `session.get(Source, source_id)` — identical
primary-key lookup, identical `None` result, identical 404. `Source` is now
unused in `routes.py` and was dropped from its `models` import, which is the
mechanical proof the handler no longer touches the table.

Verified afterwards that `routes.py` contains no `select(`, `session.get`,
`delete(` or `update(` at all.

## I2 — a test that self-destructs on 2026-10-18

`tests/test_auth_unit.py:238` stamped a session with `NOW` (2026-09-18) and then
handed it to `get_current_user`, which compares against `datetime.now(UTC)`.
`expires_at` would have been 2026-10-18, so the test had 29 days to live.

Changed to `now=datetime.now(UTC)` and added a docstring pointing at the same
reasoning `tests/conftest.py:136-146` already carries.

**Checked the whole file for the same pattern, as instructed.** Grepped every
`create_session` and `get_current_user` call in `tests/` — this was the only
occurrence. Two neighbours look similar but are correct and deliberately so:

- `test_get_current_user_expired_token_is_401` builds its session at
  `NOW - SESSION_LIFETIME - 1 day`. That is *already* expired relative to the
  real clock and only becomes more so as time passes, so it cannot rot. Its
  docstring says exactly this.
- Everything between lines 83 and 153 passes an explicit `now` to
  `lookup_session`, which never reads the real clock. Not affected.
- `tests/conftest.py:141` and `tests/test_cli_auth.py:155` already use the real
  clock.

## I3 — email case sensitivity

Added `auth.normalize_email(email) -> str` (`email.strip().lower()`) and applied
it at the three points an address enters or is looked up:

- `find_user_by_email` — normalises the lookup value.
- `create_invite` — normalises what is stored on the `invites` row.
- `routes.post_setup`'s `User(...)` construction — the one place a `users.email`
  is written. Normalised again rather than trusted from the invite row, because
  an invite issued *before* this change would still carry mixed case.

One helper rather than three copies of `.strip().lower()`, so the canonical form
cannot drift between call sites.

**Verified rather than assumed for `cli.py`.** All four CLI paths reach the
table through `find_user_by_email` — `invite`'s duplicate check, `set-password`,
`revoke-sessions`, and `post_login` — so all four became case-insensitive from
the one change, with no edit to `cli.py`. Proven by
`test_invite_rejects_a_duplicate_that_differs_only_in_case`, which drives the
real Typer command.

Tests added (4):

- `test_setup_creates_a_lowercased_account_that_logs_in_lowercased` — an invite
  for `Mixed@Case.test` produces an account whose `email` is `mixed@case.test`
  and which then logs in under that address. This is the exact scenario named in
  the brief.
- `test_login_accepts_any_case_of_a_stored_email` — the other direction, with
  surrounding whitespace too (`"  CaSeD@Example.TEST  "`), covering the `strip()`.
- `test_invite_rejects_a_duplicate_that_differs_only_in_case` — `invite
  Taken@Example.TEST` against an existing `taken@example.test` exits 1.
- `test_invite_stores_the_email_lowercased` — the `invites` row itself is
  canonical, so the account the link creates is reachable in any case.

Checked that no existing test stores a mixed-case email; every one is already
lowercase, so this is behaviour-preserving for the whole existing suite.

Also documented as a decision in `docs/architecture.md` §9, next to the
"login answers a wrong password and an unknown email identically" bullet —
that bullet is *why* this fix is needed, and the two belong together.

## I4 — README security posture and the revocation gotcha

Two additions to `README.md`:

**(a)** A new top section, above `## Accounts`, so it is read before anyone types
`invite`: the service is loopback-only, the guard is `REACHSTORE_ALLOW_NONLOCAL`,
the cookie deliberately carries no `Secure` flag, there are no CSRF tokens and no
login rate limiting, and exposing it beyond localhost means building all three
first rather than flipping the override.

**(b)** After the `set-password` / `revoke-sessions` block: use `set-password`
for a forgotten password, `revoke-sessions` when someone leaves, and **both**
after any reset prompted by a compromise — because `set-password` writes a new
hash without ending existing sessions, which stay alive for up to 30 days. It
also states why the two are separate, so a future reader does not "fix" it by
making `set-password` revoke automatically.

`set-password` behaviour was **not** changed, as instructed.

Also added one sentence noting emails are case-insensitive, since I3 changes what
an operator can expect from the `invite` argument.

## I5 — two frontend error paths bypassed 401 handling

**Chosen option: convert `startCollect` to the shared `send()` helper** (the
reviewer's stated preference), made possible by giving `ApiError` an optional
third `body` argument.

Why this over the smaller fallback: the fallback ("have `collect()` check for a
401") could not actually be written as described, because `startCollect`
returned `{ok, ...body}` and never exposed `res.status` at all — `collect()` had
no way to *see* a 401. Making the smaller fix work would have meant changing
`startCollect`'s return shape anyway, at which point converting it to `send()` is
the smaller diff and removes the one write in the app that did not throw
`ApiError`.

The 409 body is surfaced by having `send()` attach the parsed error body to the
thrown `ApiError`:

```js
if (!res.ok) throw new ApiError(res.status, res.statusText, await res.json().catch(() => null))
```

The `.catch(() => null)` is load-bearing and deliberate: a Vite proxy error page
or a dead API answers with HTML, and a bare `await res.json()` would throw a
`SyntaxError` carrying no status, replacing a truthful `ApiError(502)` with an
error `fail` cannot classify. That is the same failure mode as "an error handler
disguised a server outage as a normal logout", so it was guarded rather than
assumed away.

Both call sites:

- `Store.jsx:124` — the collect-poll's inline `catch` now calls `fail(e)` instead
  of `setError(String(e))`, so a session revoked mid-run drops to the login form.
  `fail` was added to the effect's dependency array; it is `useCallback`-memoised
  on the already-stable `onSignedOut`, so the poll does not re-subscribe.
- `Store.jsx:187` — `collect()`'s bespoke `if (!res.ok)` branch is gone. The
  `catch` keeps one branch for 409 (`e.body?.reason`), which is the only status
  carrying text worth showing; everything else, 401 included, goes through `fail`.

Every other write (`login`, `setupAccount`, `logout`, `subscribe`,
`unsubscribe`) already used `send()` and gains the richer error for free.
`Login.jsx` and `Setup.jsx` branch on `err.status`, which is untouched.

`get()` was deliberately left without body capture: no read endpoint returns a
body worth surfacing, and `ApiError.body` defaulting to `null` there is honest.

## I6 — no browser test completed a successful setup

`seed_e2e.py` now seeds an invite:

- `E2E_INVITE_EMAIL = "e2e-invitee@example.test"`, display name `E2E Invitee`,
  non-admin.
- Created with `auth.create_invite` — the public API — so the stored hash cannot
  drift from what `consume_invite` expects. No re-implementation of `_digest`.
- `now=datetime.now(UTC)`, **not** the module's fixed `NOW` (2026-09-02). `NOW`
  is well outside `INVITE_LIFETIME`, so seeding against it would have produced an
  invite that was already expired. `seed_e2e.py` is a script entrypoint, so
  reading the real clock is within the constraint.
- The raw token is written to `web/tests/.e2e-invite-token`, added to
  `.gitignore`. A fixed hardcoded token was rejected because writing its hash
  would mean duplicating `_digest` outside `auth.py`.

**Re-runnability**, which is the part that has already bitten this branch once:
each seed deletes any `User` *and* any `Invite` for that address before issuing a
new one. Both are needed — the invite is single-use, and the account the previous
run's test created would make `POST /api/auth/setup` answer 409. User deletion
cascades to sessions and subscriptions via the FKs in `models.py`. The module
docstring now records this alongside the existing subscription-reset note.

New spec `a valid setup link creates the account and lands in the store` visits
`/#setup=<token>`, sets and confirms a password, and asserts: 12 feed rows (so it
reached the store), `E2E Invitee` in `.whoami`, no admin `.badge` (invited as a
normal user), `new URL(page.url()).hash === ''` (the fragment cleared by
`history.replaceState`), and that a reload still shows the store rather than
retrying a spent link.

**Proved re-runnable by running `npm run test:e2e` twice back to back** — 13
passed both times. Output below.

## M3 — the ownership bullet covered 7 of 9 tables

`docs/architecture.md` §3. The bullet now reads "Every table that any code
touches has exactly one owning module", lists `subscriptions` among the content
tables, and states explicitly that `collectors` is declared in `models.py` and
deliberately has no owner until Plan 3. That accounts for all nine:
items / sources / subscriptions / fetch_runs / item_tags (store + query),
users / sessions / invites (auth), collectors (unowned, and said so). It also now
cites `query.get_source_by_id` as the worked example of `routes.py` staying
query-free.

**One thing fixed beyond the brief, in the same section.** The paragraph four
lines above read "**All SQL lives in `store.py` and `query.py`.** No other module
imports `sqlalchemy.select` or builds a query", presented under "These are
enforced, not aspirational." `src/reachstore/api/auth.py:16` is
`from sqlalchemy import delete, select`, so that sentence has been false since
this branch began — the same class of defect as I1, in the same section, and it
directly contradicts the bullet M3 asked me to make true. Reworded to "All
*content* SQL", with a sentence saying authentication widened the rule to one
owning module per table rather than weakening it. Flagging it here because it was
not on the list.

## M10 — the deviation register

Added item 6 to `docs/superpowers/plans/2026-09-18-auth-and-subscriptions.md`:
Ruling R5's reversal of spec §4's claim that `lookup_session` deletes expired
rows. Records both reasons — `get_session` never commits, so the delete was
discarded on every read-only request and would have looked like reclamation while
reclaiming nothing; and committing inside a per-request dependency would also
commit unrelated pending work, turning an auth check into an arbitrary
transaction boundary — plus the note that the spec's *conclusion* (no scheduler)
survives for a different reason than the spec gave.

I6 is recorded as **resolved rather than registered**, in a "Resolved rather than
recorded" note, per the instruction.

This is the only edit made under `docs/superpowers/plans/`. Nothing under
`docs/superpowers/specs/` or `docs/superpowers/reviews/` was touched.

---

## Verification

### Python suite

```
.venv/bin/pytest
============================= 206 passed in 5.52s ==============================
```

206 passed, zero warnings, zero failures. Was 202; +4 from I3's new tests. No
test was deleted or weakened. Run twice — before and after the e2e runs — with
the same result.

### e2e

Run with the port override, twice consecutively to prove re-runnability:

```
> npm run test:e2e
seeded 12 items (12 new), admin e2e-admin@example.test, and an invite for e2e-invitee@example.test into reachstore_test
[WebServer] INFO:     Uvicorn running on http://127.0.0.1:8100 (Press CTRL+C to quit)
Running 13 tests using 2 workers
  ✓  13 tests/auth.spec.js:116:1 › a valid setup link creates the account and lands in the store (261ms)
  13 passed (3.9s)

> npm run test:e2e        # immediately again, no cleanup
  ✓  13 tests/auth.spec.js:116:1 › a valid setup link creates the account and lands in the store (262ms)
  13 passed (3.7s)
```

13 passed (was 12). The second run passing unchanged is the proof the invite
reset works.

### Proof the port override was reverted

Reverted with `git checkout -- web/playwright.config.js web/vite.config.js`.

```
$ grep -rn 8100 . --exclude-dir={node_modules,.git,.venv,.superpowers,dist}
docs/superpowers/plans/2026-09-18-auth-and-subscriptions.md:2175: ... port=8100 ...
docs/superpowers/plans/2026-09-18-auth-and-subscriptions.md:3598: ... (8100/5273) ...
```

The only two hits are pre-existing prose in the preserved plan describing this
very procedure. No config file mentions 8100.

Confirmed against the committed tree rather than the worktree:

```
$ git show HEAD:web/playwright.config.js | grep 8000
40:      url: 'http://127.0.0.1:8000/api/sources',
$ git show HEAD:web/vite.config.js | grep 8000
10:    proxy: { '/api': 'http://127.0.0.1:8000' },
```

The `serve(port=8100)` edit to the webServer command was reverted by the same
`git checkout`. Port 8100 confirmed free again afterwards.

### Build

```
$ cd web && npm run build
vite v8.2.2 building client environment for production...
✓ 25 modules transformed.
dist/index.html                   0.46 kB │ gzip:  0.29 kB
dist/assets/index-Cb7h-jSN.css    3.73 kB │ gzip:  1.14 kB
dist/assets/index-C1NgGg3b.js   201.82 kB │ gzip: 63.56 kB
✓ built in 61ms
```

Clean, no warnings. (No `npm run lint` in this project, as noted.)

### The `php` processes

Both alive before and after, same PIDs, uninterrupted uptime — neither was
touched, and the API ran on 8100 throughout.

Before:
```
29601 08-10:02:07   (LISTEN 127.0.0.1:8000)
53638 10-04:42:34   (LISTEN 127.0.0.1:8001)
```

After:
```
29601 08-10:02:44 /opt/homebrew/.../php -S 127.0.0.1:8000 .../<unrelated-project>/server.php
53638 10-04:43:11 /opt/homebrew/.../php -S 127.0.0.1:8001 .../<unrelated-project>/server.php
```

`lsof` confirms both still hold their listening sockets. Elapsed time increased
monotonically, so neither restarted.

### Other constraints

- No new dependency in either language — `pyproject.toml` and `web/package.json`
  are untouched.
- No CORS middleware, no router added.
- Tenant isolation still lives only in `query.visible_to`; nothing in this diff
  goes near it.
- `routes.py` reads the clock (pre-existing, it is an entrypoint); `query.py` and
  `auth.py` still take `now` as a parameter. `seed_e2e.py` reads the real clock as
  a script, deliberately, and says why in a comment.
- The session cookie still does not set `Secure`, and that is now documented in
  three places instead of two.
- `.env` confirmed still untracked.
- Type hints on both new public functions (`get_source_by_id`, `normalize_email`).
- Working tree clean after both commits.

---

## Declined

Nothing was declined, and no instruction in the brief was found to be wrong.

Two things noticed but deliberately left alone:

1. `docs/superpowers/plans/...md:2175` says "`serve()` reads no port argument".
   That is stale — `serve(host, port)` has taken a port since it was written, and
   I used it. It is in the preserved historical record, which I may only edit for
   the M10 register, so it stays.

2. `Store.jsx`'s `loadFeed` is `useCallback(..., [])` while closing over `fail`.
   Pre-existing and currently harmless, since `fail` is memoised on a stable
   `onSignedOut` and therefore never actually goes stale. Out of scope for this
   wave, and changing it risks the `SubscriptionStrip` re-render behaviour the
   existing comment at `Store.jsx:62-67` warns about.

One judgement call worth a reviewer's eye: `web/tests/auth.spec.js` reads
`.e2e-invite-token` at module load. `npm run test:e2e` always seeds first, so the
file is always present, but a bare `npx playwright test` without seeding fails at
import with `ENOENT .e2e-invite-token` for the whole file rather than one test. I
judged the filename plus the adjacent comment self-explanatory and did not add a
guard.
