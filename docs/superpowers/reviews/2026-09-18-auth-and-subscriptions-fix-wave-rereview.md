# Fix-wave re-review — `03258dc..b1eb3e1`

Scope: the two fix commits only (`3c561b8`, `b1eb3e1`), 14 files, +278/-33.
The other 31 commits on `feat/auth-and-subscriptions` were not re-examined.
Settled design decisions listed in the brief (no `Secure` flag, no CSRF, no
rate limiting, identical 401, `lookup_session` as a pure read) were treated as
correct and are not findings.

**Verdict: READY TO MERGE.** Zero Critical, zero Important, six Minor.

---

## Verification actually performed

| Check | Result |
|---|---|
| `.venv/bin/pytest` | **206 passed in 5.61s**, no warnings summary emitted |
| Warning-free claim | Honest. The only suppression (`pyproject.toml:34`) is pre-existing, message-exact, and documented; `pyproject.toml` is untouched by this diff |
| Playwright suite | **Not run**, per instruction. Assessed by reading |
| `php` on 8000/8001 | Never contacted. Nothing was started or killed |
| Committed `web/vite.config.js:10` | `proxy: { '/api': 'http://127.0.0.1:8000' }` — revert is genuine in the committed tree, read via `git show HEAD:` |
| Committed `web/playwright.config.js:40` | `url: 'http://127.0.0.1:8000/api/sources'`, `serve()` with no port arg — genuine |
| New dependencies | None. `git diff 03258dc..b1eb3e1 -- pyproject.toml web/package.json` is empty |
| CORS middleware | None anywhere; only two comments explaining its absence |
| Tenant isolation | `query.visible_to` is still the sole predicate (`query.py:26`, called at :39, :68, :103). Nothing in this diff goes near it |
| `.env` | Untracked (`git ls-files --error-unmatch .env` → no match). No credentials added |
| Working tree | Clean |

Read-only database probe (`select count(*) filter (where email <> lower(btrim(email)))`):
dev `total=3 non_canonical=0`, test `total=0 non_canonical=0`. This matters for
Minor 1 below — the one residual risk in I3 is not realised in this environment.

---

## The eight findings

### I1 — `routes.py` built a query — **RESOLVED**

`grep -n "select|session\.get|session\.execute|session\.query|sqlalchemy|\.scalars|update\(|delete\(|insert\("`
over `src/reachstore/api/routes.py` returns exactly two lines, and neither is a
query: `:15 from sqlalchemy.orm import Session` (a type annotation) and `:205`
the `@router.delete(...)` decorator. `Source` is gone from the `models` import
(`routes.py:51` is now `from reachstore.models import Item, User`), and `Item`
survives only as the parameter type at `routes.py:95 def _summary(item: Item)`.
That import removal is the mechanical proof the handler no longer touches the
table.

`query.get_source_by_id` (`src/reachstore/query.py:169`) sits immediately after
`get_source`, wraps `session.get(Source, source_id)`, and is called from
`routes.py:198`. Behaviour is byte-identical: same identity-map-first primary-key
lookup, same `None`, same 404. Covered by the existing
`tests/test_api_subscriptions.py:99 test_subscribing_to_an_unknown_source_is_404`.

Judged on merit, not just letter: moving a `session.get` one module over is a
small change, but the invariant at stake is "`query.py` owns every read of
`sources`" and "`routes.py` builds none", and both are now true. Writing
`select(Source).where(Source.id == ...)` instead would have been strictly worse.
Correct call.

### I2 — self-destructing test — **RESOLVED, and the "only one" claim verified independently**

`tests/test_auth_unit.py:244` is now `now=datetime.now(UTC)` with a docstring
pointing at `tests/conftest.py:138-141`.

I re-ran the sweep myself rather than trusting the report, and widened it past
what the fixer checked. Every real-clock reader was enumerated first
(`get_current_user` at `auth.py`, and `routes.post_setup` which does
`now = datetime.now(UTC)` at `routes.py:326`), then every credential-minting call
in the suite was traced to see which clock stamped it:

- **`create_session`** — `tests/conftest.py:141` real clock; `tests/test_cli_auth.py:155`
  real clock; `tests/test_auth_unit.py:244` now real clock. The remaining
  fixed-`NOW` calls are `test_auth_unit.py:83, 93, 110, 119, 128, 134, 147, 148`
  and every one hands its token to `lookup_session(..., now=<explicit>)`, which
  takes `now` as a parameter and reads no clock. `:232` uses
  `NOW - SESSION_LIFETIME - 1 day`, which is already expired against the real
  clock and only gets more so. None can rot.
- **`create_invite`** — the fixer did *not* grep this, and it is the higher-risk
  one: `INVITE_LIFETIME` is 7 days, not 30, and `post_setup` reads the real clock.
  Checked anyway. `tests/test_api_auth.py:93 _invite()` already passes
  `now=datetime.now(UTC)`, so every setup test that goes through the HTTP handler
  is safe, including the two new ones. `test_api_auth.py:165` deliberately stamps
  `now(UTC) - INVITE_LIFETIME - 1 day` for the expiry case. The fixed-`NOW`
  `create_invite` calls at `test_auth_unit.py:159-201` all pass an explicit `now`
  to `consume_invite`, which is injectable.

So the claim "only one occurrence" holds, but it holds for a reason the fixer did
not check. No action needed; noted because the gap in method could have cost a
finding.

### I3 — email case sensitivity — **RESOLVED**

`auth.normalize_email` (`src/reachstore/api/auth.py`, `email.strip().lower()`) is
applied at every path an address enters or is looked up. I traced all of them
rather than accepting the list:

- `create_invite` — `Invite(email=normalize_email(email), ...)`. The only writer
  of `invites.email` (`grep -rn "Invite(" src/` returns this one construction).
- `find_user_by_email` — `select(User).where(User.email == normalize_email(email))`
  (`auth.py:232`).
- `routes.post_setup:346` — `User(email=normalize_email(invite.email), ...)`.
  Re-normalising rather than trusting `invite.email` is the right call: an invite
  row written before `3c561b8` still carries mixed case.
- `User(...)` constructions across the tree: `grep -rn "User("` over `src/` and
  `web/tests/` returns exactly `routes.py:346` and `web/tests/seed_e2e.py:91`
  (test-only, hardcoded lowercase). No third writer.
- **CLI, all four paths, verified in `cli.py` rather than assumed.**
  `invite` duplicate check (`cli.py:150`), `set-password` (`cli.py:188`),
  `revoke-sessions` (`cli.py:209`) all call `find_user_by_email`; `invite`'s write
  goes through `create_invite` (`cli.py:155`). `post_login` uses
  `find_user_by_email`. All five became case-insensitive from the one helper,
  with zero edits to `cli.py` — confirmed, `git diff 03258dc..b1eb3e1 -- src/reachstore/cli.py`
  is empty.

Normalising inside `find_user_by_email` instead of at each caller is the correct
shape: one function to audit, and the canonical form cannot drift between call
sites. Four new tests pin it in both directions including the `strip()`
(`test_login_accepts_any_case_of_a_stored_email` sends `"  CaSeD@Example.TEST  "`).

One residual gap, see Minor 1.

### I4 — README posture and the revocation gotcha — **RESOLVED**

Both sections are present: the loopback posture above `## Accounts` naming
`REACHSTORE_ALLOW_NONLOCAL` (verified against `src/reachstore/api/app.py:42,59`),
and the `set-password` / `revoke-sessions` note. Numbers check out —
`SESSION_LIFETIME = timedelta(days=30)` matches "up to 30 days",
`INVITE_LIFETIME = timedelta(days=7)` matches "valid 7 days".

`set-password` was **not** changed to auto-revoke: `cli.py:176-196` is untouched
by this diff, confirmed by an empty `git diff` on the file. The README also states
*why* the two are separate, which is the right defence against a future reader
"fixing" it.

### I5 — frontend error paths bypassing `fail` — **RESOLVED**

Both paths converted, and the two things the brief asked me to verify hold:

**The 409 still surfaces its reason.** Traced end to end.
`routes.py:73-75` declares `status_code=202, responses={409: {"model": CollectResponse}}`;
the handler sets `response.status_code = 409` and returns
`CollectResponse(started=False, reason="a collection run is already in progress")`.
`schemas.py:41-44` confirms `reason` is a real field. `api.js:37` attaches that
parsed body to the thrown `ApiError`, and `Store.jsx:195` reads
`e.body?.reason ?? 'could not start collection'`. Reason survives.

**The body parse cannot throw.** `await res.json().catch(() => null)` — the
`.catch` is on the promise, so an HTML proxy error page yields `null` rather than
a `SyntaxError` that would replace a truthful `ApiError(502)` with an unclassifiable
error. `ApiError.body` defaults to `null`, so `get()`'s two-argument construction
at `api.js:18` is still valid. The optional chain at `Store.jsx:195` covers the
`null` case.

**`fail` in the effect deps is safe**, which was the one way this change could
have silently broken the poll. `Store.jsx:68-71` memoises `fail` with
`useCallback(..., [onSignedOut])`, and `onSignedOut` is memoised in `App`. So
`[collecting, loadFeed, fail]` at `Store.jsx:131` does not re-subscribe the
2000 ms interval on every render. Had `fail` been unstable the poll would have
been torn down and rebuilt before it ever fired.

Swept the rest of the component for survivors: every `.catch` in `Store.jsx`
(`:84, :95, :123-127, :138, :152, :177, :191-196`) now routes through `fail`,
with the single deliberate 409 branch. `SubscriptionStrip.jsx:23,35` route to
`onError`, which is `fail`. No path left that shows a raw 401 in the banner.

### I6 — no browser test completed a successful setup — **RESOLVED, and genuinely re-runnable**

Assessed by reading, not executing, as instructed.

The spec's selectors were checked against `web/src/components/Setup.jsx` line by
line, since a spec that cannot pass would be the worst outcome here:
`<h1>Choose a password</h1>` matches `.auth h1`; `getByLabel('Password', {exact: true})`
resolves to `#new-password` and not to `Confirm password`;
`getByRole('button', {name: 'Create account'})` matches the submit button;
`history.replaceState(null, '', location.pathname)` fires before `onDone(me)`, so
`new URL(page.url()).hash === ''` is deterministic rather than racy by the time
the preceding auto-retrying assertions have settled. `.badge` appears exactly once
in the app (`Store.jsx:221`, `{me.is_admin && ...}`), so `toHaveCount(0)` is a
real assertion about the invitee being a non-admin, not a vacuous one.

**Re-runnability — the bug that already shipped once on this branch.** Reasoned
through rather than executed:

1. `seed_e2e.py` deletes both the `User` and the `Invite` for
   `e2e-invitee@example.test` before issuing a fresh invite. Both deletions are
   necessary and neither is sufficient: the invite is single-use, and a surviving
   account makes `post_setup` answer 409.
2. The `delete(User)` is a **bulk** ORM delete, so SQLAlchemy relationship
   cascades do *not* apply — it depends entirely on database-level
   `ON DELETE CASCADE`. Verified that is real, not just declared:
   `models.py:154` declares it, `migrations/versions/0002_auth.py:27` emits
   `sa.ForeignKey("users.id", ondelete="CASCADE")`, and
   `tests/test_schema.py:84 test_deleting_a_user_deletes_their_sessions` pins it.
   Had the cascade been ORM-only, the second run would have died on a foreign-key
   violation — which is exactly the shape of the bug that shipped before.
3. `now=datetime.now(UTC)` rather than the module's `NOW = 2026-09-02`. Correct
   and load-bearing: `NOW` is far outside `INVITE_LIFETIME`, so the fixed date
   would have seeded an invite that was already expired.
4. Failure partway through run N is also survivable: if the setup spec dies after
   consuming the invite but before creating the account, run N+1 deletes a
   nonexistent user, deletes the consumed invite, and issues a fresh one. The
   reset is unconditional, not conditional on the previous run's outcome.
5. Path resolution holds. `INVITE_TOKEN_FILE = Path("web/tests/.e2e-invite-token")`
   is repo-root-relative, and `package.json` runs `seed:e2e` as `cd .. && ...`
   before `playwright test`, so the seed's cwd is the repo root — consistent with
   the pre-existing `RAW_DIR = Path("data/raw-e2e")`. The spec side uses
   `new URL('.e2e-invite-token', import.meta.url)`, which is file-relative and
   independent of Playwright's cwd.
6. The token file is gitignored (`git check-ignore` → `.gitignore:16`) and absent
   from `git ls-files web/tests/`. No credential committed.

No cross-worker hazard introduced: `smoke.spec.js` is entirely read-only
(search, detail pane, health strip), and the invitee's feed is the 12 shared
items (`owner_user_id IS NULL`), unaffected by the admin's subscribe in
`auth.spec.js`.

### M3 — ownership bullet covered 7 of 9 tables — **RESOLVED**

`docs/architecture.md` §3 now accounts for all nine, and each claim checks out
against `models.py`'s `__tablename__` list (`users`, `collectors`, `sources`,
`subscriptions`, `items`, `fetch_runs`, `item_tags`, `sessions`, `invites` —
note the auth table really is named `sessions`, so the doc's naming is right):

- `items`, `sources`, `subscriptions`, `fetch_runs`, `item_tags` → `store.py` / `query.py`
- `users`, `sessions`, `invites` → `api/auth.py`
- `collectors` → explicitly unowned until Plan 3. **Verified**:
  `grep -rn "Collector\b" src/reachstore/` excluding `models.py` returns nothing.
  Nothing reads or writes it. The claim is true, not a convenient excuse.

### M10 — deviation register omitted a ruling reversal — **RESOLVED**

Item 6 added, recording R5's reversal of spec §4 with both reasons (the delete was
discarded because `get_session` never commits; committing inside a per-request
dependency would turn an auth check into an arbitrary transaction boundary) and
the note that the spec's *conclusion* — no scheduler — survives for a different
reason. The preamble was updated from "Both were found while writing this plan"
to distinguish items 1-5 from item 6. I6 is recorded under "Resolved rather than
recorded", which is the honest placement. Only `docs/superpowers/plans/` was
touched; nothing under `specs/` or `reviews/`.

---

## The two unbriefed changes

### 1. Rewriting the `docs/architecture.md` §3 SQL invariant — **correct, and not a weakening**

**The fixer's factual claim is true.** `src/reachstore/api/auth.py:16` is
`from sqlalchemy import delete, select`, so the old sentence — "No other module
imports `sqlalchemy.select` or builds a query", printed under the heading "These
are enforced, not aspirational" — was false from the moment auth landed. Fixing it
was right; leaving a documented invariant that the code contradicts is the same
defect class as I1, four lines above the bullet M3 asked to be made true.

**Is the reworded version true?** Yes, for `src/`. I enumerated every SQL-building
site in production code: `store.py` and `query.py` (the owners), and `api/auth.py`
at `:170, :177, :181, :186, :212, :232` — all six against `sessions`, `users`, or
`invites`, i.e. the three tables auth owns. `collect.py`, `cli.py`, `db.py`,
`deps.py`, `adapters/` import only `sqlalchemy.orm.Session` or `Engine` as type
annotations. `routes.py` builds nothing. So "All *content* SQL lives in `store.py`
and `query.py`; no other module builds a query against a content table" holds.

**Does it weaken a load-bearing invariant?** No, on inspection. The worry would be
that "no module imports `sqlalchemy.select`" was a grep-able check and "no query
against a content table" is a semantic one needing a human to classify tables. But
the grep still works in practice — `auth.py` is now the single known exception, and
a new `select(Item)` in `collect.py` would surface just as fast. More importantly
the replacement is *stronger* where it counts: "one owning module per table" is
checkable per table and catches things the old phrasing missed, such as a second
module querying `users`. The old sentence was a proxy for the real rule; the new
pair states the real rule. Good call, correctly disclosed.

### 2. `ApiError.body` + `startCollect` throw-on-error — **correct, no caller breakage**

The fixer's reasoning for preferring this over the smaller fallback is sound and I
confirmed the premise: the old `startCollect` returned `{ok, ...body}` and never
exposed `res.status`, so "have `collect()` check for a 401" was unimplementable
without changing the return shape anyway. At that point converting to `send()` is
the smaller diff and removes the one write in the app that did not throw.

**Every caller checked**, which is the part that mattered:

- `startCollect` — `grep -rn "startCollect" web/src web/tests` returns three lines:
  the definition (`api.js:85`), the import (`Store.jsx:2`), and the single call
  site (`Store.jsx:189`). Exactly one consumer, and it was rewritten in the same
  commit. No `{ok, ...}` reader survives anywhere, tests included.
- `ApiError` — every consumer reads `.status` only: `Login.jsx:21`, `Setup.jsx:32`,
  `Store.jsx:69` (`fail`), `api.js:69` (`fetchMe`'s 401→null). The constructor
  change is additive with a `null` default, so `api.js:18`'s two-argument call in
  `get()` is unaffected. Nothing read `.body` before it existed.
- The five writes that already used `send()` (`login`, `setupAccount`, `logout`,
  `subscribe`, `unsubscribe`) gain the richer error for free; `subscribe`/
  `unsubscribe` return 204 and still short-circuit at `api.js:38` before any
  `res.json()`.

Leaving `get()` without body capture is the right restraint — no read endpoint
returns a body worth surfacing, and `null` is honest.

---

## Findings

**Critical: none.**

**Important: none.**

### Minor 1 — no data migration lowercases pre-existing `users.email` rows

`src/reachstore/api/auth.py:232`, `migrations/versions/` (no new revision in this diff)

I3 normalises the *lookup* but not the rows already in the table, and
`models.py:35` makes `users.email` `unique=True` on a case-**sensitive**
`String(320)` — not `citext`, and there is no functional index on
`lower(email)`. So a `users` row written before `3c561b8` carrying
`Alice@Example.com` becomes unreachable the moment this commit lands.

Failure scenario: an account exists as `Alice@Example.com`. Alice types
`Alice@Example.com` at the login form — exactly what she was given.
`find_user_by_email` now queries `WHERE email = 'alice@example.com'`, finds
nothing, and `post_login` spends a dummy verify and returns the deliberately
identical 401. Neither Alice nor the operator can distinguish this from a wrong
password. `set-password` and `revoke-sessions` also report "No account for
Alice@Example.com". Worse, `post_setup` would then happily insert a *second*
row `alice@example.com`, because the unique constraint does not case-fold — two
accounts, one person. This is precisely the undiagnosable lockout I3 was
dispatched to prevent, inverted.

Why this is Minor and not Important: I checked rather than speculated. A
read-only `count(*) filter (where email <> lower(btrim(email)))` returns
`non_canonical=0` against both the dev database (3 users) and the test database
(0 users). The condition is not realised anywhere it can currently bite, and
every seeded, documented, and tested address is already lowercase. It is worth a
one-line guard before anyone else clones a database from an earlier commit on
this branch:
`UPDATE users SET email = lower(btrim(email));` as an alembic revision, or
compare with `func.lower(User.email)` at `auth.py:232`. Does not block merge.

### Minor 2 — `auth.spec.js` fails as a whole file, not one test, when the token is missing

`web/tests/auth.spec.js:8-11`

`fs.readFileSync` runs at module load, so an absent `.e2e-invite-token` throws
during collection and takes down all nine specs in the file with
`ENOENT`, not just the setup test.

Failure scenario: fresh clone, or anyone running `npx playwright test` directly
rather than `npm run test:e2e`. The file is gitignored, so a fresh clone never
has it. The error names the file, so it is self-diagnosing, and `web/README.md:20`
documents `npm run test:e2e` as *the* invocation — which always seeds first. The
fixer disclosed this and judged it acceptable; I agree. Moving the read inside the
test body would scope the failure to one test for two lines of diff, if you want it.

### Minor 3 — `web/README.md:30-31` is now stale

Says "The specs sign in first, using the admin account `seed_e2e.py` creates" —
no longer true of the new setup spec, which signs in *by creating* an account.
The README also does not mention the seeded invite or the `.e2e-invite-token`
file, which is the one piece of e2e state a reader would need to know about when
the file goes missing (Minor 2). Documentation only.

### Minor 4 — the reworded §3 invariant is true of `src/` but does not say so

`docs/architecture.md` §3

"No other module builds a query against a content table" is unqualified, and
`web/tests/seed_e2e.py` builds `update(Subscription)`, `delete(User)`, and
`delete(Invite)` — one content table and two auth tables — outside their owning
modules. The old wording had the same hole ("no other module imports
`sqlalchemy.select`"), and test fixtures are a normal exception, but since the
sentence sits under "These are enforced, not aspirational" and M3 was raised for
exactly this class of over-claim, the scope is worth one qualifying clause
("in `src/`"). No behavioural impact.

### Minor 5 — `routes.py:347-349` comment overstates uniqueness

The comment says "this is the one place a `users.email` is written".
`web/tests/seed_e2e.py:91` also constructs a `User`. Test-only and lowercase, so
harmless, but the comment is the sort of absolute a future reader will rely on.
"the one place in `src/`" would be accurate.

### Minor 6 — `cli.py invite` echoes the un-normalised address

`src/reachstore/cli.py:152, 171` print the raw argument
("Invite for `Alice@Example.com`", "`Alice@Example.com` already has an account"),
while `create_invite` stores `alice@example.com`. An operator running
`invite Alice@Example.com` sees confirmation in the case they typed and never
learns the stored form. Benign now that `README.md` states emails are
case-insensitive, and the invitee never types their address anyway — but echoing
`normalize_email(email)` would make the output match reality for one word of diff.

---

## On whether any of the eight fixes was the wrong call

None were. Two were worth a second look and both survive it:

- **I1** could be dismissed as moving a `session.get` one module over. It is not
  cosmetic: dropping `Source` from `routes.py`'s imports means the handler has no
  handle on the table at all, and the alternative of inlining a `select()` in
  `query.py` would have been more code for identical behaviour.
- **I5's** contract change is the largest behavioural delta in the wave and was
  unbriefed in part. It is nonetheless the smaller correct fix, for the reason the
  fixer gives and I verified: the briefed fallback could not have been written.

The fixer's two self-flagged deviations were both in-scope in spirit, both
disclosed, and both correct. Its two "noticed but left alone" items (the stale
plan prose at `:2175` — `serve(host, port)` does take a port, confirmed at
`api/app.py:56`; and `loadFeed`'s `useCallback(..., [])` closing over a stable
`fail`) are accurately characterised and correctly left alone.

---

## Verdict

**READY TO MERGE** — all eight findings are genuinely resolved, both unbriefed
changes are correct and break no caller, and the only residual (no backfill for
pre-existing mixed-case emails) is provably not realised in this environment.
