# SDD ledger — plan: docs/superpowers/plans/2026-09-18-auth-and-subscriptions.md

Spec: docs/superpowers/specs/2026-09-18-auth-and-subscriptions-design.md (read)
Branch: feat/auth-and-subscriptions, forked from main @ b3b6715
Plan commits: b3b6715 (plan), 4c0b83c (pre-flight import corrections)

## Pre-flight scan

### Pair rows — every pair of tasks sharing a file or an interface

| A | B | Shared | A produces → B consumes | Found |
|---|---|---|---|---|
| 1 | 2 | models.py | `UserSession`, `Invite`, `User.is_admin` | OK. T2 imports all three; names match T1 exactly. |
| 2 | 3 | auth.py | `hash_password`, `create_session`, `COOKIE_NAME` | OK. T3 fixtures import exactly these. |
| 2 | 4 | auth.py | `verify_password`, `create_session`, `spend_dummy_verify`, `get_current_user`, `SESSION_LIFETIME`, `COOKIE_NAME`, `delete_session` | OK. T4's import list is a subset of T2's Produces. |
| 2 | 5 | auth.py | `get_current_user`, `require_admin` | OK. |
| 2 | 6 | auth.py | `create_invite`, `hash_password`, `delete_all_sessions`, `MIN_PASSWORD_LENGTH` | OK. |
| 2 | 7 | auth.py | `consume_invite`, `hash_password`, `MIN_PASSWORD_LENGTH` | OK. |
| 3 | 4,5,7,8 | conftest.py | `make_user`, `client_for`, `anon_client`, `admin_client`, `user_client` | OK. `client_for` returns a 3-tuple `(client, user, password)`; all four consumers unpack three. Verified by grep. |
| 3 | 5 | test_api_collect.py | T3 deletes the file's local autouse `_running` reset; conftest provides it suite-wide | OK, and REQUIRED by T5 — its permission matrix touches `/api/collect` and needs the reset. |
| 4 | 5 | routes.py | T4 adds 3 auth routes; T5 adds deps to the 5 pre-existing ones | OK, disjoint edits. |
| 4 | 7 | routes.py, test_api_auth.py, schemas.py | `_set_session_cookie`, `SetupRequest`, `UserOut`, `create_session` import | OK. T4 deliberately defines `SetupRequest` early, next to `LoginRequest`. |
| 4 | 7 | test_api_auth.py | T7 appends to T4's file | MINOR: T4's tests use bare `COOKIE_NAME`, T7's use `auth.COOKIE_NAME`. Both valid; style drift inside one file. Not a defect — noted so a reviewer does not flag it as a conflict. |
| 5 | 8 | routes.py, test_api_permissions.py | T5 creates `CASES`; T8 appends 2 rows | OK. T5's `CASES` correctly omits `/api/catalog`, which does not exist until T8. |
| 5 | 8 | routes.py `get_search` | T5 adds `user` dep; T8 adds `subscribed_only` | OK. T8 Step 7 shows the FULL final signature including T5's `user` dep, so T8 cannot regress it. |
| 6 | 9 | setup URL format | T6 prints `<base>/#setup=<token>`; T9 parses `location.hash.slice(1)` via URLSearchParams | OK. `#setup=<tok>` → `URLSearchParams("setup=<tok>").get("setup")`. |
| 6 | 11 | config/seed | `WEB_BASE_URL`; T11 seeds an admin via `hash_password` | OK. |
| 8 | 10 | API endpoints | `/api/catalog`, `PUT`/`DELETE /api/subscriptions/{id}` | OK. |
| 8 | 11 | subscribed_only | T11's last e2e test exercises the T8 filter through the UI | OK. |
| 9 | 10 | Store.jsx, SearchBar.jsx, styles.css | T9 creates `Store`, `canCollect`; T10 adds `subscribedOnly`, `onSubscribedOnlyChange`, `SubscriptionStrip` | OK, sequential supersets. T10 Step 3 shows the full replacement header JSX. |
| 9 | 11 | DOM selectors | `.auth`, `.auth .error`, `.whoami`, `.badge`, "sign out", "Sign in", "Create account", `.auth h1` | OK — each verified present in T9's JSX. `getByLabel('Password', {exact:true})` is required because Setup.jsx also has "Confirm password"; T11 uses `exact` everywhere it matters. |
| 10 | 11 | DOM selectors | `.subs-summary`, `.subs-list input[type=checkbox]`, `aria-label="subscribed only"` | OK — each verified present in T10's JSX. |
| 12 | 5 | app.py / test_api_app.py | T12 rewrites the `RuntimeError` text | OK. `test_non_loopback_host_is_refused` asserts only on `"REACHSTORE_ALLOW_NONLOCAL"`, which the new text retains. Verified by reading the test. |

### Self-agreement rows — one per task

| Task | Own text agrees with itself? |
|---|---|
| 1 | Yes. Models declare `default=` AND `server_default=`, matching the migration's `server_default=sa.false()`. Test asserts exact column sets. |
| 2 | Yes, AFTER a fix: a test was named `test_session_valid_right up_to_expiry` (invalid identifier). Corrected pre-flight. `maxmem` is derived from parsed params, so the malformed-hash tests cannot fail for the wrong reason. |
| 3 | Yes, AND it carries the load-bearing subtlety explicitly: sessions must be stamped with the REAL clock, because `get_current_user` compares against `datetime.now(UTC)`. A fixed date would arrive pre-expired. |
| 4 | Yes. One acknowledged constraint exception (`select(User)` in `post_login`), flagged in the task text rather than hidden. |
| 5 | Yes. Access matrix in the task matches the spec's §7 table row for row. |
| 6 | Yes, AFTER a fix: import instructions claimed `datetime`/`get_settings` needed adding; both already exist. Corrected pre-flight (4c0b83c). `set-password` now uses `confirmation_prompt=True` per spec §6, and its three tests feed the password twice. |
| 7 | Yes. Password length is validated BEFORE `consume_invite`, and a test pins that a typo does not burn the link. |
| 8 | Yes, AFTER a fix: claimed `store.py` imports `pg_insert`; it imports bare `insert` and has no `from sqlalchemy import` line. Corrected pre-flight (4c0b83c). 204 routes return an explicit `Response` rather than `None`. |
| 9 | Yes, AFTER a fix: one JSX block was elided with `…`. Spelled out pre-flight. The Store.jsx split is justified in-task (hooks cannot be conditional). |
| 10 | NO — one self-contradiction found, see ruling P1 below. |
| 11 | Yes. Port-conflict and "never kill a process you did not start" guidance carried inline. |
| 12 | Yes. |

### Rubric conflicts — plan mandates that the review rubric treats as defects

None. No task mandates a test that asserts nothing or verbatim duplication of
a logic block. Two near-misses, both deliberate and justified in-task:
- `UserOut(...)` is constructed identically in three handlers (T4 login, T4 me,
  T7 setup). Four fields, no logic. A shared helper is reasonable; a reviewer
  raising it should be treated as Minor, not as duplication of a logic block.
- `signIn()` credentials are duplicated between `seed_e2e.py` and the two spec
  files (T11). Unavoidable across a Python/JS boundary; T12 Step 3 mandates
  documenting that they must stay in step.

## Rulings

Ruling P1 (pre-flight, Task 10 Step 2) — Task 10 Step 2 said "change `submit`
so toggling the box re-runs an active search" and then, in the same sentence,
"`Store` owns that, so `SearchBar` only reports the change." Those contradict:
the re-run belongs to `Store.changeSubscribedOnly`, which Step 3 already
implements, so `SearchBar.submit` needs no change at all. Decided: SearchBar
gets ONLY the checkbox and the two new props; `submit` is untouched. Removing
the sentence rather than adding a second re-run path, because two components
both re-running the query would fire duplicate requests on every toggle.
Cost if wrong: near zero — if toggling turns out not to re-run the search, the
one-line fix is in `changeSubscribedOnly`, which is already the owner.

## Execution

Task 1: dispatched (base a7596de, model sonnet)
Task 1: implemented DONE (commit 80ac9a6, 119/119 passing, pristine)
Task 1: review dispatched (a7596de..80ac9a6, model sonnet)
Pre-verified (controller, while Task 1 review ran): Task 3's premises all hold —
  local make_client() exists in test_api_read/sources/collect (lines 14/27/23);
  test counts are exactly 7/4/7 = 18 as the plan claims; the autouse _running
  reset is test_api_collect.py:11-20; .item-list exists in ItemList.jsx for the
  Task 9/11 selectors. No plan correction needed.
Pre-verified: Task 8's premise holds — query.search already implements
  subscribed_only as an inner JOIN on Subscription requiring active.is_(True)
  (src/reachstore/query.py). This also confirms the soft-delete unsubscribe
  design: active=False drops rows from a subscribed_only search without
  destroying subscriptions.label. No plan correction needed.
Task 1: review ✅ spec compliant, Approved; 1 Important (plan-mandated), 1 Minor.
Task 1: Ruling R1 — reviewer is RIGHT and the plan was wrong. Invite.is_admin was
  written with default=False only, while migration 0002 creates it with
  server_default=sa.false(). That is the same model/migration parity defect the
  task's own constraints call out for User.is_admin, applied inconsistently to
  its twin. Not a runtime bug (create_invite always passes is_admin explicitly),
  but `alembic revision --autogenerate` would propose a spurious change. Decided:
  FIX — one line, and it makes the two booleans consistent. Plan text corrected
  too so the doc and the code agree. Cost if wrong: near zero, one line revert.
Task 1: Ruling R2 — reviewer's ⚠️ was caused by MY constraints block, which said
  "sessions.user_id and invites foreign keys use ondelete=CASCADE". `invites` has
  no FK by design (no invited_by column). The reviewer checked task-2-brief and
  correctly resolved it as not-a-gap. Not a code finding; my reviewer prompt was
  sloppy. Future reviewer prompts must not imply an FK on invites.
Task 1: Minor (deferred): test_schema.py duplicate User setup at 2 call sites —
  defensible YAGNI, surfaced to the final review.
Task 1: fix round 1 dispatched (resumed original implementer; finding =
  Invite.is_admin server_default + a parity-pinning test)
Pre-verified: Task 2's crypto premises hold on this machine — scrypt
  n=2**15 r=8 p=1 runs in 40 ms (plan claimed 41); _maxmem(n,r)=128*n*r*2
  gives 64 MB against a 32 MB requirement; encoding yields exactly 6
  $-separated fields; all 5 malformed-hash cases in the parametrised test
  are caught by (AttributeError, ValueError, TypeError). No correction needed.
Task 1: fix round 1 complete (commit 1da6e16, 120/120 pristine).
  Implementer correctly OVERRULED my fix instruction with proof: I asked for a
  DB-reflection check, but this suite's schema comes only from Alembic
  migrations, never Base.metadata — so reflecting the DB would show the
  migration's (always-correct) server_default and could never detect the
  model's omission. They added model-level assertions instead and verified by
  reverting the fix and watching it fail. My instruction was wrong; theirs is
  right. Second time an implementer has overruled a brief with evidence.
Ruling R3 (controller, pre-Task-9) — my plan told Tasks 9/10/12 to run
  `npm run build && npm run lint`. There IS no lint script: web/package.json
  defines only dev/build/preview/seed:e2e/test:e2e and the repo has no eslint
  config. Decided: DROP the lint step rather than add ESLint — the global
  constraints forbid new dependencies and a linter is not part of an auth
  slice. `vite build` is the build gate. Cost if wrong: unused imports go
  uncaught by tooling; the task reviewer reads the diff and would catch them.
Task 1: re-review — all findings ADDRESSED, no new breakage. Re-reviewer
  independently confirmed the implementer's pushback was correct and my
  instruction was wrong (conftest builds schema via alembic only; reflection
  could never catch a model-level omission).
Task 1: complete (commits a7596de..1da6e16, review clean)

Task 2: dispatched (base d0b8afd5ff6913baf094630f183cf34c0328b630, model sonnet)
Task 2: implemented DONE (commit bac790c, 142/142 passing, pristine)
Task 2: controller pre-checks before review — grep confirms auth.py references
  NO content tables (Item/Source/FetchRun/ItemTag) and reads the clock exactly
  once, at auth.py:204 inside get_current_user. Both binding constraints hold.
Task 2: review dispatched on OPUS (d0b8afd..bac790c) — security boundary of the
  whole slice; asked it to judge 8 named crypto/session failure modes on the
  code rather than the comments (constant-time compare, per-password salt,
  dklen from stored digest, expiry boundary <= vs <, digest-only storage,
  invite single-use, expired-row deletion vs rollback, dummy-verify global).
Pre-verified (controller probes, run and then deleted; tree left clean):
  - monkeypatch.setattr(session, "close", lambda: None) WORKS on a SQLAlchemy
    Session instance -> Task 6's cli_session fixture is sound.
  - TestClient persists cookies across requests -> Tasks 4/7 "login then /me on
    one client" assertions are valid.
  - A FastAPI Cookie() parameter whose NAME differs from the cookie reads None
    silently -> the param must be spelled `reachstore_session`. Task 4's note
    on this is load-bearing, not decorative.
  - pyproject.toml already filters the starlette/httpx TestClient deprecation
    warning by exact message, so new TestClient usage cannot break the
    warning-free requirement.
Task 2: review (opus) — ✅ spec compliant on every constant/interface/boundary;
  Task quality: Needs fixes. 0 Critical. 3 Important, 7 Minor.
  Reviewer confirmed independently: no timing leak, no plaintext token, no auth
  bypass; and proved the dklen=0 edge raises rather than bypassing.
Task 2: ⚠️ warning-free — RESOLVED by controller: 142/142, no warnings summary.
Task 2: ⚠️ "does a caller use spend_dummy_verify / MIN_PASSWORD_LENGTH" — not a
  Task 2 gap; those callers are Task 4 (post_login) and Tasks 6/7. Carried
  forward to the Task 4 and Task 7 dispatches.
Task 2: Ruling R4 — Important #1 (get_current_user/require_admin have zero test
  coverage) ACCEPTED. Plan-mandated: my brief's test file omitted them. These
  two functions ARE the security boundary; an inverted `if user.is_admin`
  passes all 142 tests today. Fix. Cost if wrong: none, tests are additive.
Task 2: Ruling R5 — Important #2 (expired-session delete never persists)
  ACCEPTED, but fixing it the OTHER way than the reviewer's first option.
  Verified myself: deps.get_session yields then close()s, and close() rolls
  back, so the DELETE is discarded on any read-only request. Rejected
  "commit the delete": committing inside a dependency that runs on EVERY
  request would also commit unrelated pending work in that request-scoped
  session, and a GET should not write. Decided: REMOVE the delete and the
  false "no scheduled job needed" claim. Expired rows are inert because the
  `expires_at <= now` check re-runs every lookup; at 5-50 users with 30-day
  sessions the volume is negligible. This also dissolves Minor #3
  (StaleDataError on concurrent delete) by deleting the code that raises it.
  Cost if wrong: expired rows accumulate; a cleanup command is a later,
  separate change.
Task 2: Ruling R6 — Important #3 (bare except wraps hashlib.scrypt) ACCEPTED.
  A wrong _maxmem for raised cost params would turn every verify into False —
  a total auth outage presenting as "wrong password", with no exception and no
  failing test. Narrow the try to parsing only. Cost if wrong: none.
Task 2: Minors accepted into the same round (all one-liners, all clearly right):
  spend_dummy_verify early-return (first call costs 2x a real verify, in the one
  function whose purpose is timing equalization); Cookie(alias=COOKIE_NAME) —
  I verified myself that a mismatched param name reads None SILENTLY, so this
  is a real footgun not a style point; exact-boundary expiry assertions to pin
  `<=` against a regression to `<`.
Task 2: Minor (deferred to final review): consume_invite read-then-write race
  (bounded by the users.email unique constraint, low real risk on localhost);
  `result.rowcount or 0` does not normalize a -1 driver return.
Task 2: fix round 1 dispatched (resumed original implementer).
Task 2: fix round 1 complete (commit c4938ed, 151/151 passing, pristine).
  Implementer mutation-tested each fix (inverted admin check, <= -> <, simulated
  scrypt fault) — confirmed failing before and passing after.
  Divergence accepted: cookie param renamed reachstore_session -> token with
  alias=COOKIE_NAME. I verified experimentally that the alias drives the lookup
  and the param name is then free, so this is cosmetic and arguably clearer
  than my plan snippet. Deferred items confirmed untouched (rowcount still at
  auth.py:172, no with_for_update added) — good scope discipline.
Task 2: re-review dispatched (d26a9ee..c4938ed, sonnet), told not to
  re-litigate the two items I verified myself.
Task 2: re-review — all 6 findings ADDRESSED, no new breakage. Re-reviewer
  confirmed the dependency tests assert .status_code explicitly (401 vs 403),
  so an inverted admin check cannot hide behind a bare pytest.raises.
Task 2: Minor (deferred to final review): Important-3's fix is correct by
  inspection, but no COMMITTED test proves "a real scrypt fault propagates
  rather than being swallowed" — only the 5 parsing-failure cases are covered.
  The implementer's mutation check for it was manual/ad-hoc and its report is
  honest about that. A re-wrap regression would go undetected.
Task 2: complete (commits d0b8afd..c4938ed, review clean, 1 deferred minor)

Task 3: dispatched (base c4938ed8244dd917c8767b5f68162fbc53d1bd9c, model sonnet)
Task 3: implemented DONE (commit bd45dda, 151 -> 151, zero warnings)
Task 3: controller pre-checks all pass — (1) only tests/ touched, no src/ edit;
  (2) all three local make_client helpers removed; (3) local autouse fixture
  gone, only conftest.py:92 remains; (4) conftest.py:141 stamps sessions with
  datetime.now(UTC) while the user row keeps a fixed created_at at :118 —
  exactly the split that avoids the delayed-expiry time bomb; (5) counts still
  7/4/7.
Task 3: review dispatched (c4938ed..bd45dda, sonnet). Told it not to re-verify
  the five checks above, and to spend its pass on the one thing they cannot
  answer: an assertion-by-assertion audit of all 18 retrofitted tests, with a
  weakened/deleted assertion rated Critical (silent coverage loss across the
  whole API surface). Also flagged a specific way these tests could pass for
  the wrong reason: if client_for built its own Session instead of reusing the
  injected one, data seeded in a test body would be invisible to the handler.
Ruling R7 (controller, latent plan defect found during a health check) —
  my plan documented `.venv/bin/alembic upgrade head` bare, but
  migrations/env.py:15 reads os.environ["DATABASE_URL"] and does NOT load
  .env, so that command fails with KeyError. It did not bite during Task 1
  (the implementer evidently exported it; dev DB verified at 0002 with
  sessions/invites/users.is_admin all present), but anyone following the plan
  or the README later would hit it. Decided: document the required export in
  both Task 1 Step 6 and the Task 12 README section. Cost if wrong: none,
  it is a documentation correction.
Health check passed: dev DB at 0002 (head); legacy row id=1
  hand-verify@example.com has an empty hash and verify_password("") returns
  False — Task 2's design working as intended, no migration special case.
  .env still untracked.
Task 3: review — ✅ spec compliant, Approved. 0 Critical, 0 Important, 2 Minor.
  Reviewer audited all 18 tests individually, read two files directly where the
  diff package cut hunks mid-function, and cross-checked the package against a
  fresh git diff (185 lines each, zero delta) to prove completeness. Every
  assertion byte-identical. Specifically confirmed client_for and the test body
  share one Session object, so the suite passing is real evidence not a false
  positive from divergent sessions.
Task 3: Minor (deferred to final review): (1) test_api_sources.py:38 drops an
  unused `session` param that the analogous collect tests keep — inconsistent
  micro-edit, functionally inert; (2) conftest anon_client duplicates 3 lines
  of app/override construction from client_for — worth factoring only if a
  third client-builder appears.
Task 3: complete (commits c4938ed..bd45dda, review clean, 2 deferred minors)

Task 4: dispatched (base 45da999dadd91f005df7dbfab5a2817b7b5f1da8, model sonnet)
Pre-verified (for Task 8): on fastapi 0.141.1 / starlette 1.6.0 BOTH 204 forms
  behave identically — `status_code=204, response_class=Response` returning
  Response(status_code=204), and the naive `-> None` returning None, each give
  204 with an empty body and no content-length. So the plan's explicit form is
  version-proofing, not a necessity on this stack. Recorded as evidence in case
  a reviewer flags the explicit form as unnecessary ceremony: it is a defensible
  choice either way, and I will adjudicate rather than pre-judge it in the
  reviewer prompt.
Task 4: implemented DONE (commit 892239f, 159/159 passing, pristine).
  Implementer chose find_user_by_email() in auth.py over the inline select()
  my brief allowed — the better option: routes.py now contains NO select( at
  all, so the documented "one deliberate constraint exception" I planned for
  is not needed. Tasks 6/7 reuse the helper. Also factored _user_out(), removing
  the triplicated UserOut construction from my plan snippet.
Task 4: controller pre-checks all pass — spend_dummy_verify called on the
  unknown-email branch (routes.py:200); cookie sets httponly/samesite=lax/
  path=/ /max_age and NO secure (routes.py:169-176); routes.py query-free;
  DEFAULT_USER_ID left intact for Task 5; Cookie(alias=COOKIE_NAME) used in
  both routes.py:216 and auth.py:220.
Task 4: review dispatched (45da999..892239f, sonnet). Told it not to re-verify
  those five, and to spend the pass on: whether the two 401s are REALLY
  indistinguishable (body + headers, not just status), logout edge cases,
  session commit ordering vs cookie set, _set_session_cookie reusability for
  Task 7, whether /me leaks password_hash, and whether the indistinguishability
  test actually compares the two responses rather than asserting 401 twice.
Ruling R8 (controller, pre-Task-5) — my plan's Task 5 Step 8 and Task 12 Step 5
  both grep DEFAULT_USER_ID across all of docs/. A full-repo scan returns ~25
  hits, and almost all are in docs/superpowers/{specs,plans,reviews}/ from
  Plan 1 — an immutable historical record deliberately preserved in f978ec2.
  An implementer following "make this grep clean" could start rewriting the
  decision record, falsifying how the system got here. Decided: scope both
  greps to src/, tests/, web/src/, and docs/architecture.md, and state
  explicitly that the superpowers specs/plans/reviews are not to be edited.
  docs/architecture.md:147 is the ONLY living doc needing the update, and that
  is Task 12's job. Cost if wrong: none — narrowing a verification command.
Task 4: review — ✅ spec compliant, Approved. 0 Critical, 0 Important, 3 Minor.
  Confirmed: both 401 paths byte-identical (same status, same detail, NO cookie
  on either branch); commit ordering create_session -> commit -> set_cookie so
  a token is never handed out for an uncommitted row; _user_out + response_model
  give two independent filters against password_hash leakage; the
  indistinguishability test really compares wrong.json() == unknown.json().
Task 4: reviewer corrected ME, fairly — my "silent footgun" framing overstated
  it. A MISMATCHED Cookie param name does read None silently (I probed that),
  but the plan's param was spelled identically to COOKIE_NAME's value, so the
  alias is better practice, not a fix for an active bug. Noted for accuracy.
Task 4: Minor (deferred to final review): (1) post_logout's `if token is not
  None` guard is unreachable, since get_current_user already 401s on a missing
  cookie — harmless belt-and-braces; (2) no explicit "log out twice on the same
  client" test (traced correct, but uncovered); (3) the report slightly
  overstates the footgun, per above.
Task 4: complete (commits 45da999..892239f, review clean, 3 deferred minors)

Task 5: dispatched (base bf8179ebbbda51e79333bc127b8b621969105766, model sonnet)
Pre-verified (for Task 6): typer.prompt(hide_input=True, confirmation_prompt=True)
  behaviour probed directly —
    two matching lines  -> exit 0, password captured (the plan's format: correct)
    mismatched lines    -> exit 1, "The two entered values do not match."
    SINGLE line         -> exit 1 (input starvation)
    short password x2   -> exit 1, reaches the length check
  This retroactively validates the spec-compliance fix I made during plan
  self-review: adding confirmation_prompt=True WITHOUT also changing the test
  inputs from one line to two would have broken three Task 6 tests. Both halves
  of that change were needed; both are in the plan.
  (Note: a single-command Typer app rejects the command name as an argument and
  exits 2 — irrelevant to cli.py, which has many commands, but it cost one
  probe iteration to notice.)
Task 5: implemented DONE (commit e25d9fe, 171 passing, 0 warnings, +12 tests).
Task 5: controller pre-checks — DECISIVE result: `git diff` across the three
  retrofitted test files is COMPLETELY EMPTY. All 18 tests passed untouched
  when the auth requirement turned on. That is the Task-3-before-Task-5
  ordering validating itself: no retrofit bug could hide inside an auth bug,
  and no assertion had to be weakened to keep the suite green.
  Also confirmed: DEFAULT_USER_ID gone from src/tests/web except the assertion
  of its absence; NO docs/ file touched (historical record intact, per R8);
  all five legacy endpoints gated (_admin on sources+collect, get_current_user
  + user_id=user.id on feed/search/items); only 4 files changed.
Task 5: review dispatched on OPUS (bf8179e..e25d9fe) — the authorization
  boundary; a silent failure is a cross-tenant leak. Told it the mechanical
  change is trivial and its effort belongs on whether the new tests PROVE what
  they claim: specifically, would test_api_tenant_http.py still pass if
  query.visible_to were neutered to allow everything? Also asked it to confirm
  404-not-403 is asserted for a REAL item owned by someone else (not just a
  nonexistent id), that the matrix distinguishes 401 from 403 exactly rather
  than accepting any 4xx, and that the collect stub actually takes effect so
  the suite makes no network call.
Task 5: review (opus) — ✅ spec compliant, Approved. 0 Critical, 0 Important,
  5 Minor. ISOLATION PROOF AUDIT: the tests are genuine mutation detectors —
  they would FAIL if query.visible_to were neutered. Set EQUALITY at
  test_api_tenant_http.py:58-59 (not containment), empty-list equality at :87,
  and 404-not-403 asserted against a REAL item first proven reachable at 200
  (:72-75), so it cannot pass vacuously. Reviewer also confirmed the collect
  stub patches the module attribute routes.py:84 resolves at call time, so no
  network call fires; and that the matrix pins exact status codes, so a fully
  inverted auth could not pass.
Ruling R9 — of the 5 Minors, THREE are folded into Task 8 rather than deferred,
  because Task 8 is the first task to add new endpoints and is therefore the
  moment the matrix's own promise gets tested: (a) add a route-enumeration test
  so "a new endpoint with no row" actually fails, with a documented EXEMPT set;
  (b) make no_op_collect clear _running like the real run_collection's finally
  does, so a second POST inside one test cannot get an unexplained 409;
  (c) label the matrix tuples so a failure names the role instead of printing
  a TestClient repr. Plan updated and task-8-brief regenerated. Cost if wrong:
  small, these are additive test changes inside a task that already edits that
  file. Deferring instead would have let Task 8 ship three endpoints past a
  safety net that does not yet work.
Task 5: Minor (deferred to final review): app.py:19-23 and :33-36 still say
  "there is no authentication in this slice" — now false. Already covered by my
  Task 12 Step 1, which the reviewer found independently; good corroboration.
Task 5: Minor (deferred): test_an_unknown_cookie_is_401_not_500 re-implements
  the anon_client fixture inline (inherited from my brief, not introduced).
Task 5: complete (commits bf8179e..e25d9fe, review clean, 2 deferred minors)

Task 6: dispatched (base d2b79774a234d0e48045805181c09bd8640a78b4, model sonnet)
Task 6: implemented DONE (commit e025355, 179 passing, 0 warnings, +8 tests).
  Used find_user_by_email in all three commands rather than raw SQL, keeping
  cli.py free of SQL against users/sessions/invites.
Task 6: controller pre-checks pass — no select/delete/update in cli.py; link
  uses the /#setup= FRAGMENT form (cli.py:172); web_base_url at config.py:13
  and WEB_BASE_URL at .env.example:9; dev DB now holds one PENDING admin
  invite for you@example.com (unconsumed); .env untracked, tree clean.
  Confirmed .superpowers/ is gitignored, so recording the live token below
  does not commit a credential.
Task 6: SETUP TOKEN FOR TASK 7 (dev DB, single-use, localhost only):
  http://127.0.0.1:5173/#setup=bkSH_0e_Uxh5jz7_A219cbxNvTwSRH1-hwxUOXZzP1Q
  token = bkSH_0e_Uxh5jz7_A219cbxNvTwSRH1-hwxUOXZzP1Q
Task 6: review dispatched (d2b7977..e025355, sonnet). Focus areas given: token
  printed exactly once and never logged; invite refuses an email that already
  has an account (privilege-escalation path if not); set-password's length
  check runs before any write; revoke-sessions filters by user_id and cannot
  log out the whole instance; failure paths consistent and no commit on
  failure; whether neutering session.close in the fixture could mask a real
  session leak; and whether tests prove behaviour (does the new password
  actually verify?) rather than just exit codes.
Task 6: review — ✅ spec compliant, Approved. 0 Critical, 0 Important, 4 Minor.
  Reviewer confirmed the two dangerous ones are safe: delete_all_sessions
  filters where(UserSession.user_id == user_id) (auth.py:157-159), so
  revoke-sessions cannot log out other users; create_invite stores only
  _digest(token) and nothing re-echoes the raw value. Also noted set-password's
  length check runs BEFORE _session() is called, so a rejected password
  provably never touches the DB — stronger than "left equal by luck".
Task 6: Minor (FLAGGED FOR FINAL REVIEW — cross-cutting, not Task 6's fault):
  emails are stored and compared with no case normalisation, so
  Taken@Example.test and taken@example.test are different accounts. Affects
  find_user_by_email, invite's duplicate check, login, and Task 7's collision
  check. Thin threat model (invites are issued by someone with shell access)
  but it means the duplicate-account guard can be sidestepped by changing case.
  Inherited from Task 2. Surface to the user at the end.
Task 6: Minor (deferred): cli_session neuters session.close so a future missing
  close() would go undetected (all three commands do call it correctly today);
  two session-lifecycle styles now coexist in cli.py (new try/finally vs the
  pre-existing commands'); the 4-line lookup-then-exit-1 shape repeats twice —
  correctly left unfactored per rule-of-three.
Task 6: complete (commits d2b7977..e025355, review clean, 4 deferred minors)

Task 7: dispatched (base e025355ceed64887f14fed748f15d16fdc26eee0, model sonnet)
Task 7: implemented DONE (commit 30add14, 187 passing, 0 warnings, +8 tests).
  Implementer took both authorised deviations: find_user_by_email instead of an
  inline select(), and reused _user_out instead of hand-building UserOut. Both
  correct — routes.py remains query-free.
Task 7: GUARDRAIL HELD. Port 8000 was occupied by an unrelated php process
  (PID 29601 — the SAME Laravel server an agent killed during the previous
  slice). This agent left it alone and used port 8100 instead, then stopped
  its own server cleanly. Verified: PID 29601 still LISTENing; 8100 clear.
Task 7: controller pre-checks — routes.py query-free; 400 at :271/:275 for
  token failures and 409 at :283 for email collision; password length checked
  at :270 BEFORE consume_invite at :273 (so a typo cannot burn the link);
  dev DB now has you@example.com is_admin=True with a verifying password, and
  its invite is marked consumed; the legacy hand-verify row still cannot log in.
Task 7: WORKING CREDENTIALS for Tasks 9-11 hand-verification and e2e:
  you@example.com / Reachstore-Setup-2026!  (dev DB, localhost only)
Task 7: review dispatched (e025355..30add14, sonnet). Told it the two
  deviations were pre-authorised. Focus: is the 400 message truly identical
  across all four token-failure paths; is the consumed invite COMMITTED before
  the 409 raises (otherwise it un-consumes on rollback and the link becomes
  infinitely retryable — the subtlest risk in the task); is the session
  committed before the cookie is set; exactly one set_cookie in routes.py;
  is_admin carried from invite to user; and do the tests prove single-use
  end-to-end plus that a rejected short password leaves the invite redeemable.
Task 7: review — ✅ spec compliant, Approved. 0 Critical, 0 Important, 2 Minor.
  Reviewer traced the subtlest risk and confirmed it correct: session.commit()
  runs BEFORE the 409 raises, so the consumed invite is durably spent even when
  account creation is rejected — the link cannot be retried forever. Also
  verified the 400 detail is the IDENTICAL literal across all four token-failure
  paths (traced through auth.consume_invite, which returns None uniformly for
  unknown/consumed/expired); exactly one set_cookie in the whole codebase;
  is_admin carried invite->user; and both hard properties proven END-TO-END
  (redeem-then-redeem-again for single use; reject-short-then-redeem-same-token
  for the ordering guarantee). The 405-vs-404 RED anomaly was validated as a
  real environment artifact: web/dist exists, so pre-implementation the POST
  fell through to the StaticFiles mount, which serves only GET/HEAD.
Task 7: Minor (deferred to final review): routes.py is now 298 lines / 9
  endpoints, with ~120 lines of self-contained auth surface — a split into
  api/routes_auth.py is worth considering IF more auth surface arrives, but is
  explicitly a suggestion not a defect at current size. Also, post_setup rebinds
  the local name `token` (session token) after using body.token (invite token);
  not a bug, but two security-sensitive tokens sharing a name in one function.
Task 7: complete (commits e025355..30add14, review clean, 2 deferred minors)

Task 8: dispatched (base 30add1415b8c22ec2d2e712bb5a3a03dae0121ce, model sonnet)
Task 8: implemented DONE (commit 3eaeeb5, 187 -> 202 passing, 0 warnings).
Ruling R10 — the implementer overruled my Step 9 code and was RIGHT on BOTH
  counts. I verified each independently before accepting:
  (1) create_app().routes exposes ONLY /api/openapi.json and /api/docs on
      fastapi 0.141.1 — include_router wraps the sub-router in an opaque node
      with no .path. My route-enumeration test, added specifically to stop the
      matrix's promise being aspirational, would ITSELF have asserted nothing.
      router.routes yields all 11 real endpoints; that is what they used.
  (2) A route .path is a template (/api/items/{item_id}) while CASES holds
      concrete paths (/api/items/999999). String equality never matches, so
      every templated route would have read as "missing". They added a
      wildcard-regex comparison.
  This is the 6th time an implementer has corrected a brief of mine with proof.
  Plan corrected at 6f9cadf so it documents what actually works. Cost if wrong:
  none — the correction is verified by direct execution, not argument.
Task 8: review dispatched (30add14..3eaeeb5, sonnet). Told it both corrections
  are confirmed, and asked the NEXT question instead: is the replacement
  actually load-bearing — would it fail if a new /api/* endpoint were added
  with no CASES row; is EXEMPT too broad; can the regex over-match. Also asked
  it to check catalog's LEFT JOIN yields one row per source even with multiple
  subscription rows, that the catalog leaks no health field (exact key set +
  extra="forbid"), that /api/feed is genuinely untouched, and that subscribe is
  idempotent at the DB level with no read-then-insert.
Task 8: review — ✅ spec compliant, Approved. 0 Critical, 0 Important, 2 Minor.
  Reviewer independently traced a hypothetical new endpoint through the FIXED
  enumeration test and confirmed it would fail; verified EXEMPT uses exact
  string matches so it cannot swallow a future sibling like /api/collect/status;
  verified the regex is anchored and [^/]+ cannot cross a slash. Confirmed the
  catalog's one-row-per-source guarantee is STRUCTURAL (the (user_id, source_id)
  unique constraint means the outer join matches 0 or 1 rows), not merely
  untested. Idempotency is DB-level with no read-then-insert anywhere.
Task 8: Minor (FLAGGED FOR FINAL REVIEW, my design not the implementer's):
  the route-enumeration test matches by PATH ONLY, not method. `covered` is
  built from CASES paths with the method discarded, and my brief deliberately
  declined to give PUT /api/subscriptions/{id} its own row, relying on the
  DELETE row's path coverage. So a future new METHOD on an already-covered path
  (e.g. PATCH /api/subscriptions/{id}) would ship with no permission assertion.
  Narrows what "the failure this file exists to catch" actually catches.
Ruling R11 — Task 8 made query.py's source_health docstring stale: it justifies
  not scoping by subscriptions because "that table has no write path yet", which
  this task just falsified. Behaviour is still correct (source_health is the
  admin diagnostics view and is deliberately global). Decided: fold a
  docstring-only correction into Task 12, which is already the stale-prose task
  (it fixes the same class of staleness in app.py). Not a fix round — no
  behaviour changes. Cost if wrong: none, it is a comment.
Task 8: complete (commits 30add14..3eaeeb5, review clean, 2 deferred minors)

Task 9: dispatched (base 6f9cadf64d077f9ce317c6024eb9990597ea3701, model sonnet)
Task 9: implemented DONE (commit a59bf2d, 8 files, build clean).
  Hand-verified in a REAL browser via Playwright MCP: API on 8100, Vite on
  5173, both started and killed by the agent. It went beyond the checklist and
  redeemed a real invite end to end — Setup form -> fragment cleared from the
  address bar -> landed in Store as a NON-admin, with badge/HealthStrip/Collect
  correctly absent. That last part independently exercises Task 8's admin
  gating from the browser side.
Task 9: controller pre-checks — working tree CLEAN (the temporary
  vite.config.js proxy edit was reverted); BOTH pre-existing php processes
  alive and untouched (8000 PID 29601, 8001 PID 53638); agent's own servers on
  8100/5173 stopped; package.json and lockfile unchanged (no new deps); no
  react-router; all six ref names present in Store.jsx. App.jsx -206 lines /
  Store.jsx +202 is the signature of a move, not a rewrite.
Task 9: review dispatched (ed6e345..a59bf2d, sonnet). Framed move fidelity as
  THE question: compare the removed App.jsx body against the added Store.jsx
  line by line and find anything beyond the five intended changes — a useRef
  silently becoming useState, a generation-counter check dropped from a branch,
  the loadMore in-flight guard weakened, the polling effect's dep array
  altered, searchingRef assignments lost, or a ref comment trimmed. Also asked
  for: the three-state gate (undefined/null/object) so no login flash on
  reload; fetchMe returning null ONLY for 401 and rethrowing 500s; signOut
  clearing state in finally not then; Setup clearing the spent token from the
  address bar; and any new XSS surface (the previous slice found a javascript:
  href hole in ItemDetail).
Task 9: review — ✅ spec compliant; MOVE FIDELITY EXACT. Reviewer diffed the
  removed App.jsx body against the new Store.jsx line by line: all nine
  useState, all six useRef guards and their comments preserved
  CHARACTER-FOR-CHARACTER, mount effect and polling dep arrays unchanged,
  loadMore/collect in-flight guards intact, no generation-counter check
  dropped. Exactly the five intended differences, nothing more. Also confirmed
  no XSS surface, ApiError used consistently, Setup clears the spent fragment,
  and signOut uses finally. Hand-verification judged credible (concrete PIDs,
  ports, a real health string, a real invite redeemed).
  Task quality: Needs fixes — 1 Important (plan-mandated), 3 Minor.
Task 9: Ruling R12 — Important (App.jsx:22) ACCEPTED, and it is MY defect.
  fetchMe() is correct (null only for 401, rethrows the rest), but my call site
  `.catch(() => setMe(null))` collapses every rethrown error into "signed out".
  A 500 or a dropped connection would render a login form during an outage with
  no signal at all. Decided: add a distinct bootError state and render a banner
  ABOVE the form rather than replacing it — the failure may be transient, so
  still let them try to sign in, but never disguise an outage as a normal
  signed-out visit. Plan corrected. Cost if wrong: trivial, one state + one
  conditional banner.
Task 9: Minor (deferred to final review): startCollect still returns {ok,...}
  instead of throwing ApiError like every other write, so collect() carries a
  bespoke branch — predates this task, inconsistency this task extended without
  questioning; Login.jsx/Setup.jsx duplicate the busy/error/.auth shell (fine
  at two call sites, a third would justify extracting); `me`'s shape is accepted
  with no runtime check.
Task 9: fix round 1 dispatched (resumed original implementer).
Task 9: fix round 1 complete (commit df4ca3a, build clean). Implementer
  verified LIVE rather than by reasoning: pointed the Vite proxy at a dead port
  (9999) so /api/auth/me returned 502, and confirmed the banner "Could not
  reach the server: Error: 502 Bad Gateway" rendered ABOVE a still-usable
  Login form. Then reverted vite.config.js and killed its own processes.
  Chose to clear bootError in signedOut(), reasoning that a deliberate sign-out
  proves the server is reachable so a stale outage banner must not outlive it —
  sound, and it wrote the reasoning into the code as a comment.
Task 9: controller pre-checks — tree clean, vite.config.js reverted; both php
  processes alive (8000/8001); nothing left listening on 5173/8100/9999.
Task 9: scoped re-review dispatched (a59bf2d..df4ca3a, sonnet). Asked it to
  trace BOTH paths (401 -> clean login form with no banner; non-401 -> banner
  above a usable form), confirm the three-state gate survived the restructure
  (no fourth state, no login flash), confirm the Setup branch still works
  inside the new fragment, and judge the clear-on-signout reasoning.
Task 9: re-review — finding ADDRESSED, no new Critical/Important breakage.
  Re-reviewer traced both paths: a 401 makes fetchMe() RETURN null (no throw),
  so .catch never runs and the form is clean; any non-401 rethrow lands in
  .catch and renders the banner above a usable form. Judged the live proxy-to-
  dead-port evidence credible.
Task 9: Minor (deferred to final review): signedOut() clears bootError
  unconditionally, but Store's signOut calls it from a `finally` — so signing
  out WHILE the server is down also clears a stale banner, where the
  "proves reachability" reasoning does not hold. Narrow (needs boot-fail ->
  successful login -> server down again -> click sign out), self-correcting on
  reload, cannot resurrect the original defect.
Task 9: Out-of-scope noted for final review: Store's signOut has a bare
  `finally` with no .catch, so a failed logout() produces an unhandled promise
  rejection in the console. Pre-existing, untouched by this task.
Task 9: complete (commits ed6e345..df4ca3a, review clean, 5 deferred minors)

Task 10: dispatched (base df4ca3ad76e827446d59c5feee611eac2ae5b3ce, model sonnet)
Task 10: implemented DONE (commit 3c2ee86, build clean). Hand-verified in a
  live browser via Playwright with NETWORK CAPTURE proving /api/feed never
  receives subscribed_only — stronger than a source grep. API on 8100, Vite on
  5173, vite.config.js reverted, .playwright-mcp/ scratch cleaned up.
Task 10: controller pre-checks — RULING P1 HONOURED: SearchBar's submit is
  byte-for-byte unchanged, so only Store.changeSubscribedOnly re-runs the
  query and no toggle fires duplicate requests. subscribed_only appears only
  in fetchSearch, never fetchFeed. Both guards are refs not state (reqIdRef,
  pendingRef). reload() is awaited after each toggle — no optimistic update.
  Tree clean; both php processes alive; nothing stray on 5173/8100; no new deps.
Task 10: review dispatched (df4ca3a..3c2ee86, sonnet). Asked it to verify the
  guards are CORRECT not merely present: does reload() capture the incremented
  id and only apply a matching response; does toggle add to pendingRef BEFORE
  any await with no await between check and add (or a same-tick double click
  still doubles); does the finally always clear so a thrown request cannot
  wedge a row; and is there a path where a toggle's own reload is discarded by
  a later one leaving a stale checkbox. Also: does changeSubscribedOnly pass
  the NEW flag explicitly rather than reading batched-stale state; is
  lastQueryRef cleared on return to the feed; does onError={fail} route a 401
  to the login form; and is `identifier` rendered as text not into an href
  (the previous slice found a javascript: hole in ItemDetail).
Task 10: review — ✅ spec compliant; CONCURRENCY GUARD AUDIT: both guards
  CORRECT under traced interleavings. reqIdRef increments synchronously before
  the async call and only applies a matching response; pendingRef's check and
  add are synchronous with no await between them, so a same-tick double click
  on one row IS blocked, and the finally always clears so a thrown request
  cannot wedge a row. Also confirmed changeSubscribedOnly passes `next`
  explicitly (avoiding the React-batching trap), lastQueryRef is cleared in
  loadFeed, identifier renders as text (no XSS), and the toggle is a real
  button with accessible names on the checkboxes.
  Task quality: Needs fixes — 1 Important (plan-mandated), 2 Minor.
Task 10: Ruling R13 — Important ACCEPTED, and it is MY defect. Store's `fail`
  is a plain arrow, so every Store render gives it a new identity;
  SubscriptionStrip's reload is useCallback(..., [onError]) with an effect keyed
  on [open, reload], so selecting an item or a poll tick re-fires
  fetchCatalog() while the strip is open. State stays correct (reqIdRef
  resolves it) but it wastes a request per incidental re-render, defeating the
  guard's stated intent. Decided: FIX at the root — wrap `fail` in useCallback
  with [onSignedOut], which App already memoises. One line, no change needed in
  SubscriptionStrip. Cost if wrong: trivial and revertible.
Task 10: Minor (CARRY TO TASK 11): each row checkbox's accessible name is the
  WHOLE label — "identifier tier N · kind" — not just the identifier. My Task 11
  e2e selects via `.subs-list input[type="checkbox"]`, a CSS selector, so it is
  unaffected; but anyone switching to getByLabel must use the composite text.
Task 10: Minor (deferred to final review): Store.jsx keeps accumulating
  concerns (feed, search, collect, subscriptions) — small increment here, but a
  trend worth a later consolidation pass.
Task 10: fix round 1 dispatched (resumed original implementer).
Task 10: fix round 1 complete (commit 609c8f0, build clean). Browser
  re-verified with exactly the evidence asked for: /api/catalog fires ONCE on
  opening the strip and does NOT re-fire across two subsequent item selects.
  Both php PIDs identical before and after.
  Implementer also answered the dependency-array question instead of silently
  editing: loadFeed ([]) and refreshSources ([me.is_admin]) both reference
  `fail` without listing it, and it argued neither needs it because fail's
  behaviour was always invariant — it closes only over the already-stable
  onSignedOut and the stable setError setter. Reported rather than changed,
  which is what I asked for.
Task 10: controller pre-check — the fix's PREMISE holds: App.jsx:35 defines
  signedOut with useCallback, so [onSignedOut] genuinely stabilises `fail`
  rather than relocating the churn. Tree clean, no strays.
Task 10: scoped re-review dispatched (3c2ee86..609c8f0, sonnet). Asked it to
  verify fail is genuinely stable and behaviourally identical, to JUDGE the
  implementer's dependency-array reasoning and say plainly whether it agrees
  (naming a concrete failure if not), and to assess whether "two item selects
  with no catalog call" is sufficient evidence that the effect no longer
  re-fires on unrelated re-renders.
Task 10: re-review — finding ADDRESSED, no new breakage. Re-reviewer confirmed
  the chain terminates in a genuinely stable reference (App.jsx:35 signedOut is
  useCallback with [] deps) rather than relocating churn, and that fail's body
  is byte-identical so there is no behavioural regression. AGREED with the
  dependency-array reasoning, with a sharper argument: fail's only free
  variables (onSignedOut, setError) are stable for the mount's lifetime, so
  every fail closure ever created is behaviourally interchangeable — adding it
  to those arrays would be "a no-op change dressed as a fix". Noted the browser
  check exercised the select path but not the poll-tick path, and that this is
  fine because useCallback compares the dep array, not the render's cause.
Task 10: complete (commits df4ca3a..609c8f0, review clean, 2 deferred minors)

BLOCKER IDENTIFIED for Task 11 — web/playwright.config.js starts its API
  webServer on port 8000 with reuseExistingServer:false, but port 8000 is held
  by the user's php process (PID 29601). The e2e suite cannot run as configured.
  The previous slice hit this exact wall and solved it with a TEMPORARY port
  override (8100/5273) reverted afterwards. Task 11's dispatch carries explicit
  instructions to do the same and to never touch php.

Task 11: dispatched (base 609c8f0b22f247eb82ca4c841ddc421c02feaa2e, model sonnet)
Task 11: implemented DONE (commit b8eba45). 12/12 e2e passing, verified across
  TWO consecutive full runs — which is the point, because the repeatability was
  itself the bug they found.
Task 11: BLOCKER HANDLED CORRECTLY. Ran the API on 8100 (Vite kept 5173, which
  was free), then reverted. Controller-verified: playwright.config.js is back to
  the 8000 probe, vite.config.js proxy back to 8000, and grep finds NO 8100/5273
  leakage anywhere in web/, src/, or tests/. Both php PIDs (29601, 53638) alive
  before and after. They even did a final run against the REVERTED 8000 config
  and confirmed it fails to bind rather than interfering with php — which proves
  the revert is genuine, not cosmetic.
Task 11: two evidence-backed deviations, both catching real problems in MY design:
  (1) seed_e2e.py now resets the e2e user's subscriptions each run. Because
      unsubscribe is a SOFT delete (flips active, never removes the row), after
      one full run the e2e user still has a subscriptions row, so a SECOND
      `npm run test:e2e` would start with something subscribed and fail the
      "nothing subscribed" precondition. My seed was not idempotent across runs.
  (2) The subscription test uses .click() + expect().toBeChecked() rather than
      .check(). .check() asserts checked state immediately with no retry, but
      Task 10's checkbox is deliberately NON-optimistic — it re-reads the
      catalog from the server after each toggle — so there is a real ~15-20ms
      window where the box is not yet checked. They reproduced the race with a
      timing probe before changing it. This is a direct interaction between two
      of my own decisions (non-optimistic UI + .check()'s no-retry semantics).
Task 11: controller pre-checks — playwright still pinned 1.61.1 (no bump, no
  `playwright install`); Python suite still 202 passing; tree clean; 4 files.
Task 11: review dispatched (609c8f0..b8eba45, sonnet). Told it NOT to run the
  e2e or Python suites (shared database, minutes-long run). Asked it to judge
  both deviations on their merits rather than accept the report — in particular
  whether deviation 2 is a legitimate race fix or papers over a UI bug that
  belongs in the component — and to audit that all four retrofitted smoke tests
  kept their original assertions, especially the javascript: URL test that
  guards a real XSS hole from the previous slice.
Task 11: review — ✅ spec compliant, Approved. 0 Critical, 0 Important, 2 Minor.
  Reviewer verified BOTH deviations independently against the real source, not
  the report: store.py:90-100 confirms unsubscribe never deletes (its own
  docstring says "The row survives"), and SubscriptionStrip.jsx:28-39 confirms
  toggle awaits the write THEN awaits reload() — TWO chained round trips before
  the DOM updates, so the race is worse than the implementer described.
  RETROFIT AUDIT: all four smoke tests kept every original assertion; the only
  change is goto -> signIn. The javascript: XSS guard still has its route
  interception registered BEFORE navigation. Credentials consistent across all
  three files; getByLabel('Password', {exact:true}) used at all ~9 sites.
Task 11: Minor folded into Task 12 (it is the docs task): seed_e2e.py's module
  docstring still claims idempotency only via upsert_items and does not mention
  the new subscription reset.
Task 11: Minor (deferred to final review): signIn is duplicated ~6 times inline
  across auth.spec.js rather than shared — verbatim brief content, and
  spec-file self-containment is a defensible Playwright convention.
Task 11: complete (commits 609c8f0..b8eba45, review clean, 1 deferred minor)

Task 12: dispatched (base b8eba45aaa11661124ddb412c4af9ae7bd044dbd, model sonnet)
Task 12: implemented DONE_WITH_CONCERNS (commit ac86902, 7 files, +153/-24).
  Python suite 202 passing 0 warnings (run 3x). npm run build clean.
  seed_e2e.py run twice to confirm the new reset is idempotent.
  SKIPPED npm run test:e2e and DISCLOSED it plainly: port 8000 held by php
  PID 29601 (verified still listening, untouched); Task 11 had verified 12/12
  across two runs immediately prior; this task touches no executable code.
  I consider that skip justified and correctly reported rather than claimed.
Task 12: four judgement calls, TWO of them corrections to MY brief:
  (a) README.md had no "setup instructions" section for the new content to
      follow — it was a one-line placeholder. Added ## Accounts after the title.
  (b) My brief said credentials are duplicated in "both files"; they are in
      THREE (seed_e2e.py, smoke.spec.js, auth.spec.js). Documented all three.
  (c) My brief's Step 6 git-add list omitted query.py and seed_e2e.py even
      though Steps 1b/3b require editing them. Staged both anyway — correct.
  (d) Also corrected adjacent stale facts in architecture.md that directly
      contradicted content being added in the same sections: table count 7->9,
      test count 116->202, and a stray "No authentication..." line in §7.
      This is scope expansion; flagged to the reviewer for judgement.
Task 12: controller pre-checks — historical archive INTACT (the only
  docs/superpowers change in range is my own plan edit); Python diff is
  docstrings and message strings only, no logic; test_api_app.py untouched and
  its 3 tests pass, so REACHSTORE_ALLOW_NONLOCAL survived the rewrite; suite
  202; tree clean; php alive.
Task 12: review dispatched (b8eba45..ac86902, sonnet). Framed the standard as
  "is every sentence TRUE of the code today", told it that verifying a doc
  claim against its source is legitimately its job here, and gave it a list of
  specific claims to check against named files (cookie flags, no CSRF, no rate
  limiting, digest-only sessions, invites having no FK, every route declaring a
  dependency with no middleware, scrypt params, spend_dummy_verify on the
  unknown-email branch, the /#setup= fragment format, and the Alembic env note).
Task 12: review — ❌ 2 Important accuracy defects; everything else verified TRUE
  against source. Reviewer checked each documented claim against the named file
  (cookie flags, no CSRF/rate-limiting, digest-only sessions, invites having no
  FK, all 12 routes declaring a dependency with zero middleware, routes.py
  building no SQL, scrypt params, spend_dummy_verify on the unknown-email
  branch, CLI flags, /#setup= fragment, Alembic reading os.environ not .env) —
  all TRUE. Judgement calls 1-3 independently re-verified correct, including
  that README.md really was a one-line file since the initial commit.
Task 12: Ruling R14 — both Important findings ACCEPTED; this task's entire bar
  is "is every sentence true", and both sentences are not:
  (1) query.py:241-242 — the SAME false "once subscriptions have a write path"
      premise survives in a SECOND paragraph of the docstring Step 1b was
      written to fix, and now contradicts the paragraph directly above it that
      correctly describes /api/catalog's per-user narrowing as existing.
  (2) architecture.md:81-91 — "Nine tables." sits above a table listing seven
      rows, because sessions/invites went in as prose. Self-inflicted by the
      otherwise-correct scope expansion; a reader counting rows gets 7 vs 9.
  Cost if wrong: nil, these are prose corrections.
Task 12: reviewer CORRECTED my framing of judgement 4 — the §8 "no
  authentication in front of it" edit was NOT scope creep. The brief's own Step
  5 grep would have matched that exact lowercase phrase and failed the sweep if
  left alone, so that edit was mandatory. Only the table-count fix needed more
  care. Recorded so the final review does not re-litigate it.
Task 12: Minor (deferred to final review): §3/§9 use `- **bold**` bullets where
  surrounding invariants use bare `**bold**` paragraphs (implementer flagged
  this transparently rather than silently reformatting); README's Accounts
  section does not mention the loopback-only constraint, which is exactly the
  fact an operator needs before exposing the service; set-password and
  revoke-sessions are listed with no explanation of when to use them. All three
  trace to my brief's template.
Task 12: fix round 1 dispatched. Also gave the implementer a SHARPER sweep for
  the re-run — case-insensitive and extended to "no write path" — since that is
  precisely what would have caught defect (1) the first time.
Task 12: fix round 1 complete (commit 2d25703). Both Important findings fixed.
  query.py now reads "...which is why per-user scoping now lives in
  /api/catalog rather than here" — agrees with the paragraph above instead of
  contradicting it; source_health's BODY is byte-identical (behaviour unchanged).
  architecture.md §4 now reads "Seven content tables, plus the two
  authentication tables described below" — honest against the 7 table rows,
  and 7+2 reconciles with the 9 model classes.
  Controller re-ran both sweeps independently: clean. Suite 202, tree clean.
Task 12: scoped re-review dispatched (ac86902..2d25703, sonnet). Asked it to
  rule out a THIRD stale occurrence in the source_health docstring (the first
  fix missed a second, so that is the failure mode), to verify 7+2 reconciles
  with 9 model classes, and to check whether "content tables" is actually the
  right label for all seven rows — if one of them is users or collectors, the
  new sentence would be subtly wrong in a different way.
Task 12: re-review — both original findings ADDRESSED at the sentence level,
  but the fix INTRODUCED a new Important inaccuracy, which is exactly the risk
  I asked the re-reviewer to check for. "Seven content tables" mislabels
  `users` — which architecture.md:69-71 classifies ten lines earlier as one of
  "the three auth tables" — and `collectors`, which is infrastructure metadata.
  Same document, two contradictory classifications nine lines apart. The
  inaccuracy was relocated, not eliminated.
  Confirmed good: no third stale "write path" occurrence anywhere in query.py;
  source_health's new sentence is factually true (/api/catalog really does
  filter Subscription.user_id == user_id); 7 rows + 2 prose = 9 model classes.
Task 12: Ruling R15 — ACCEPTED. Fixing by dropping the classification from the
  count sentence entirely rather than trying to find a label that fits all
  seven rows: the §3 taxonomy covers only 7 of 9 tables and does not mention
  collectors or subscriptions at all, so ANY collective label reused here would
  be wrong for something. A sentence that just counts cannot misclassify.
  Fix round 2 of a permitted 5. Cost if wrong: nil, it is one sentence.
Task 12: fix round 2 complete (commit 03258dc). §4 now opens "Nine tables. The
  seven below, plus `sessions` and `invites`, which are described after the
  table." — it counts and asserts no classification, so it cannot misclassify.
  Controller verified independently: the ONLY remaining table classification in
  the document is §3 line 71 ("The three auth tables (users, sessions,
  invites)"), which is accurate; `users` is never called a content table
  anywhere; stale-claim sweep clean; suite 202; tree clean.
Task 12: scoped re-review dispatched (2d25703..03258dc, sonnet) — third version
  of this one sentence, so the bar is simply "is it finally correct and did it
  break anything". Asked it to confirm the wording asserts NO category at all
  (a loose implication would be the defect relocating a third time), that it
  agrees with line 71, that the "Sharing model" prose after the table does not
  re-introduce a group label, and that the sentence still sets expectations
  BEFORE the reader counts rows — the original complaint, which must not have
  been traded away in fixing the label.
Task 12: re-review — ADDRESSED, no new breakage. Confirmed the sentence asserts
  NO category ("the seven below" is positional, carries no noun that could be
  wrong), that 7 rows + 2 prose = the 9 __tablename__ values in models.py, that
  §3's auth-tables line is now the only classification anywhere and has nothing
  left to contradict it, that the "Sharing model" prose does not re-introduce a
  group label, and that the original reader-confusion complaint is resolved
  rather than traded away.
Task 12: complete (commits b8eba45..03258dc, review clean, 3 deferred minors)

=== ALL 12 TASKS COMPLETE ===
Final state: 202 Python tests passing with zero warnings; 12 Playwright tests
passing (last verified at Task 11, twice consecutively); working tree clean.

=== FINAL WHOLE-BRANCH REVIEW (opus, b3b6715..03258dc, 31 commits) ===
Verdict: READY TO MERGE WITH FIXES. **ZERO Critical.** Reviewer enumerated all
  twelve routes and confirmed none reaches data without an identity; is_admin
  has no request-side write path (settable only from an invites row, settable
  only from cli --admin); tenant filtering is visible_to and nowhere else;
  revoke-sessions -> 401 closes end to end. 6 Important, 11 Minor.
Reviewer CAUGHT A DEFECT IN MY OWN ARTIFACT: deferred-and-rulings.md claimed
  sixteen rulings and contained seven, with Ruling P1 truncated mid-sentence.
  My extraction regex matched "Ruling ..." at line start but most rulings were
  written "Task N: Ruling ...". A reviewer working only from that file would
  have judged nine rulings it never saw. Regenerated correctly. This was a real
  process failure on my part, not a code issue.
Reviewer CHALLENGED NO RULING — read all 16 and upheld each, with three
  qualifications: (a) R5 is right but its paper trail is incomplete (spec §4
  still asserts the removed delete-on-expiry behaviour, and the deviation
  register does not list the reversal); (b) R3 (no ESLint) was the right trade,
  but the predicted cost DID materialise — loadFeed's missing `fail` dependency
  shipped, which exhaustive-deps would have caught; (c) the Task 8 path-not-
  method self-flag was correct to raise and correct not to block on, because
  the gap is currently empty.

=== FINAL FIX WAVE (dispatched, opus, BASE 03258dc) ===
ONE dispatch carrying the complete findings list, per the skill -- not one
  fixer per finding. Eight items: I1 (session.get in routes.py -> query.py),
  I2 (test self-destructs 2026-10-18), I3 (email normalisation), I4 (README
  loopback posture + set-password does not revoke), I5 (two Store.jsx error
  paths bypass `fail`), I6 (no browser test completes setup), M3 (ownership
  list covers 7 of 9 tables), M10 (deviation register missing the R5 reversal).
Model opus, not a cheaper tier: I3 silently changes auth behaviour and the
  wave touches the auth boundary across eight files. Escalation rule applies
  -- this is judgement work, not transcription.
Port rule carried verbatim. Confirmed before dispatch: php PID 29601 (:8000,
  8d uptime) and PID 53638 (:8001, 10d) both alive. I6 needs the e2e suite,
  so the dispatch carries Task 11's 8100 override-then-revert procedure and
  requires `grep -rn 8100 .` proof that the committed config still reads 8000.
Dispatch also carries the standing invitation to overrule with evidence.
  Implementers have correctly overruled me eight times on this branch; I3 and
  I6 are the two most likely to be wrong in the details.

=== FINAL FIX WAVE: LANDED (3c561b8, b1eb3e1) ===
All eight findings fixed, none declined. Python 202 -> 206 passing, zero
  warnings. Playwright 12 -> 13, and the fixer ran the e2e suite TWICE back to
  back specifically to prove the I6 invite reset is re-runnable -- the exact
  bug that shipped once already on this branch. Build clean.
Port revert verified by me independently, not taken on trust: `git show
  HEAD:web/vite.config.js` and `HEAD:web/playwright.config.js` both read 8000.
  php PIDs 29601 and 53638 alive with unbroken uptime.
Secret scan on the diff: clean. `.env` still untracked. The e2e invite token
  is written to a git-IGNORED file rather than committed -- correct instinct,
  a real invite token is a credential even in a test database.
I5 resolved better than I specified. My brief offered a fallback ("have
  collect() check for a 401") that the fixer showed was NOT WRITABLE: the old
  startCollect returned {ok, ...} and never exposed res.status, so collect()
  could not have seen a 401 to check for. My fallback was fiction. It took the
  real fix -- convert to send(), carry the 409 reason on a new ApiError.body --
  and guarded the error-body parse with .catch(() => null) so a proxy HTML
  error page cannot downgrade a status-carrying ApiError into a bare
  SyntaxError. That guard was not in my brief. Ninth correct overrule.
Two unbriefed changes, both self-disclosed: (a) reworded architecture.md §3's
  neighbouring "no other module imports sqlalchemy.select" claim, which is
  false at api/auth.py:16 and contradicted the very bullet M3 asked to make
  true; (b) the ApiError.body/startCollect contract change above. Both sent to
  the re-review for independent judgement rather than accepted on my say-so.

=== SCOPED RE-REVIEW (dispatched, opus, 03258dc..b1eb3e1) ===
ONE re-review, per the skill -- scoped to the two fix commits only, with the
  31 already-reviewed commits explicitly out of scope and the four settled
  design decisions listed as non-findings so it cannot re-litigate them.
Opus rather than a cheaper tier despite being a small diff: I3 silently
  changes auth behaviour, the startCollect contract change is unbriefed, and
  this is the last gate before a merge decision.
Told explicitly NOT to run the e2e suite -- pytest's engine fixture drops the
  test schema, so a concurrent run corrupts both suites. Read-and-reason only.

=== SCOPED RE-REVIEW: READY TO MERGE (0 Critical, 0 Important, 6 Minor) ===
All eight findings independently confirmed genuinely resolved, not cosmetically
  touched. Both unbriefed changes upheld on merit: auth.py:16 really does
  import select (so the old invariant was false), and startCollect has exactly
  one caller with every ApiError consumer reading only .status.
Re-reviewer went BEYOND its brief and was right to: I asked it to verify my
  create_session sweep; it also swept create_invite unprompted -- a 7-day
  lifetime read by a real clock, the higher-risk twin of the pattern I2 was
  about. Clean, but I had not thought to ask. It also proved I6's re-runnability
  the hard way: the seed's bulk delete(User) skips ORM cascade, so it only works
  because the DB-level cascade is real (0002_auth.py:27, pinned by
  test_schema.py:84). Had that been ORM-only, run two dies on a FK violation.
Ruling R16 -- residual minors ADJUDICATED, not deferred wholesale (3bea3a3).
  Fixed five, parked one. Rationale: M1 (no backfill for mixed-case rows) is
  the only one with teeth -- it inverts I3 into the exact lockout I3 existed to
  prevent, plus a duplicate-account bug, because users.email is case-SENSITIVE
  unique and not citext. Zero rows need it in either DB (I verified rather than
  trusting: non_canonical=0 on dev's 3 users), so it is insurance against a
  clone from an earlier commit on this branch, not a live repair. M4/M5/M6 are
  one-clause changes and M3 a doc update -- but they are the SAME defect class
  the reviewer raised M3 for (invariants over-claiming past `src/`), so fixing
  M3 alone and leaving its neighbours false would have been incoherent.
  Cost if wrong: migration 0003 is one idempotent UPDATE; a case-only collision
  makes it fail loudly on the unique constraint, which is the right outcome.
  PARKED M2 (auth.spec.js reads the token at module load, so a missing file
  fails nine specs not one): fixer and re-reviewer both judged it acceptable,
  the error names the missing path, and the M3 README change now explains it.
Did these myself rather than dispatch: the fix loop is over, and a dispatch to
  change four comments and a doc costs more than it de-risks. The migration was
  the one real change, so it got the real check -- applied to dev (0 rows moved,
  as predicted), applied on a fresh schema by the test suite's upgrade-to-head,
  and the new CLI echo test was verified to FAIL against the unfixed command
  before being kept. 206 -> 207 passing, zero warnings.
STATE: branch feat/auth-and-subscriptions, HEAD 3bea3a3, 34 commits off
  b3b6715. 207 Python tests, 13 Playwright tests. Tree clean. Dev DB at 0003.
NEXT: present the 16 rulings to the user, then finishing-a-development-branch.
  MERGE/PUSH REQUIRES EXPLICIT USER APPROVAL AND HAS NOT BEEN GIVEN.
