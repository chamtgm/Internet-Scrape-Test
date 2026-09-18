# Deferred minors and controller rulings — auth and subscriptions branch

16 rulings, 20 deferred-minor entries.
(An earlier version of this file under-reported the rulings because the
extraction regex missed the `Task N: Ruling ...` form. Caught by the final
whole-branch reviewer. Regenerated.)

## Rulings

Ruling P1 (pre-flight, Task 10 Step 2) — Task 10 Step 2 said "change `submit`
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
Ruling R3 (controller, pre-Task-9) — my plan told Tasks 9/10/12 to run
  `npm run build && npm run lint`. There IS no lint script: web/package.json
  defines only dev/build/preview/seed:e2e/test:e2e and the repo has no eslint
  config. Decided: DROP the lint step rather than add ESLint — the global
  constraints forbid new dependencies and a linter is not part of an auth
  slice. `vite build` is the build gate. Cost if wrong: unused imports go
  uncaught by tooling; the task reviewer reads the diff and would catch them.
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
Ruling R7 (controller, latent plan defect found during a health check) —
  my plan documented `.venv/bin/alembic upgrade head` bare, but
  migrations/env.py:15 reads os.environ["DATABASE_URL"] and does NOT load
  .env, so that command fails with KeyError. It did not bite during Task 1
  (the implementer evidently exported it; dev DB verified at 0002 with
  sessions/invites/users.is_admin all present), but anyone following the plan
  or the README later would hit it. Decided: document the required export in
  both Task 1 Step 6 and the Task 12 README section. Cost if wrong: none,
  it is a documentation correction.
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
Ruling R11 — Task 8 made query.py's source_health docstring stale: it justifies
  not scoping by subscriptions because "that table has no write path yet", which
  this task just falsified. Behaviour is still correct (source_health is the
  admin diagnostics view and is deliberately global). Decided: fold a
  docstring-only correction into Task 12, which is already the stale-prose task
  (it fixes the same class of staleness in app.py). Not a fix round — no
  behaviour changes. Cost if wrong: none, it is a comment.
Task 9: Ruling R12 — Important (App.jsx:22) ACCEPTED, and it is MY defect.
  fetchMe() is correct (null only for 401, rethrows the rest), but my call site
  `.catch(() => setMe(null))` collapses every rethrown error into "signed out".
  A 500 or a dropped connection would render a login form during an outage with
  no signal at all. Decided: add a distinct bootError state and render a banner
  ABOVE the form rather than replacing it — the failure may be transient, so
  still let them try to sign in, but never disguise an outage as a normal
  signed-out visit. Plan corrected. Cost if wrong: trivial, one state + one
  conditional banner.
Task 10: Ruling R13 — Important ACCEPTED, and it is MY defect. Store's `fail`
  is a plain arrow, so every Store render gives it a new identity;
  SubscriptionStrip's reload is useCallback(..., [onError]) with an effect keyed
  on [open, reload], so selecting an item or a poll tick re-fires
  fetchCatalog() while the strip is open. State stays correct (reqIdRef
  resolves it) but it wastes a request per incidental re-render, defeating the
  guard's stated intent. Decided: FIX at the root — wrap `fail` in useCallback
  with [onSignedOut], which App already memoises. One line, no change needed in
  SubscriptionStrip. Cost if wrong: trivial and revertible.
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
Task 12: Ruling R15 — ACCEPTED. Fixing by dropping the classification from the
  count sentence entirely rather than trying to find a label that fits all
  seven rows: the §3 taxonomy covers only 7 of 9 tables and does not mention
  collectors or subscriptions at all, so ANY collective label reused here would
  be wrong for something. A sentence that just counts cannot misclassify.
  Fix round 2 of a permitted 5. Cost if wrong: nil, it is one sentence.

## Deferred minors

Task 1: Minor (deferred): test_schema.py duplicate User setup at 2 call sites —
  defensible YAGNI, surfaced to the final review.
Task 2: Minors accepted into the same round (all one-liners, all clearly right):
  spend_dummy_verify early-return (first call costs 2x a real verify, in the one
  function whose purpose is timing equalization); Cookie(alias=COOKIE_NAME) —
  I verified myself that a mismatched param name reads None SILENTLY, so this
  is a real footgun not a style point; exact-boundary expiry assertions to pin
  `<=` against a regression to `<`.
Task 2: Minor (deferred to final review): consume_invite read-then-write race
  (bounded by the users.email unique constraint, low real risk on localhost);
  `result.rowcount or 0` does not normalize a -1 driver return.
Task 2: Minor (deferred to final review): Important-3's fix is correct by
  inspection, but no COMMITTED test proves "a real scrypt fault propagates
  rather than being swallowed" — only the 5 parsing-failure cases are covered.
  The implementer's mutation check for it was manual/ad-hoc and its report is
  honest about that. A re-wrap regression would go undetected.
Task 3: Minor (deferred to final review): (1) test_api_sources.py:38 drops an
  unused `session` param that the analogous collect tests keep — inconsistent
  micro-edit, functionally inert; (2) conftest anon_client duplicates 3 lines
  of app/override construction from client_for — worth factoring only if a
  third client-builder appears.
Task 4: Minor (deferred to final review): (1) post_logout's `if token is not
  None` guard is unreachable, since get_current_user already 401s on a missing
  cookie — harmless belt-and-braces; (2) no explicit "log out twice on the same
  client" test (traced correct, but uncovered); (3) the report slightly
  overstates the footgun, per above.
Task 5: Minor (deferred to final review): app.py:19-23 and :33-36 still say
  "there is no authentication in this slice" — now false. Already covered by my
  Task 12 Step 1, which the reviewer found independently; good corroboration.
Task 5: Minor (deferred): test_an_unknown_cookie_is_401_not_500 re-implements
  the anon_client fixture inline (inherited from my brief, not introduced).
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
Task 7: Minor (deferred to final review): routes.py is now 298 lines / 9
  endpoints, with ~120 lines of self-contained auth surface — a split into
  api/routes_auth.py is worth considering IF more auth surface arrives, but is
  explicitly a suggestion not a defect at current size. Also, post_setup rebinds
  the local name `token` (session token) after using body.token (invite token);
  not a bug, but two security-sensitive tokens sharing a name in one function.
Task 8: Minor (FLAGGED FOR FINAL REVIEW, my design not the implementer's):
  the route-enumeration test matches by PATH ONLY, not method. `covered` is
  built from CASES paths with the method discarded, and my brief deliberately
  declined to give PUT /api/subscriptions/{id} its own row, relying on the
  DELETE row's path coverage. So a future new METHOD on an already-covered path
  (e.g. PATCH /api/subscriptions/{id}) would ship with no permission assertion.
  Narrows what "the failure this file exists to catch" actually catches.
Task 9: Minor (deferred to final review): startCollect still returns {ok,...}
  instead of throwing ApiError like every other write, so collect() carries a
  bespoke branch — predates this task, inconsistency this task extended without
  questioning; Login.jsx/Setup.jsx duplicate the busy/error/.auth shell (fine
  at two call sites, a third would justify extracting); `me`'s shape is accepted
  with no runtime check.
Task 9: Minor (deferred to final review): signedOut() clears bootError
  unconditionally, but Store's signOut calls it from a `finally` — so signing
  out WHILE the server is down also clears a stale banner, where the
  "proves reachability" reasoning does not hold. Narrow (needs boot-fail ->
  successful login -> server down again -> click sign out), self-correcting on
  reload, cannot resurrect the original defect.
Task 9: Out-of-scope noted for final review: Store's signOut has a bare
  `finally` with no .catch, so a failed logout() produces an unhandled promise
  rejection in the console. Pre-existing, untouched by this task.
Task 10: Minor (CARRY TO TASK 11): each row checkbox's accessible name is the
  WHOLE label — "identifier tier N · kind" — not just the identifier. My Task 11
  e2e selects via `.subs-list input[type="checkbox"]`, a CSS selector, so it is
  unaffected; but anyone switching to getByLabel must use the composite text.
Task 10: Minor (deferred to final review): Store.jsx keeps accumulating
  concerns (feed, search, collect, subscriptions) — small increment here, but a
  trend worth a later consolidation pass.
Task 11: Minor folded into Task 12 (it is the docs task): seed_e2e.py's module
  docstring still claims idempotency only via upsert_items and does not mention
  the new subscription reset.
Task 11: Minor (deferred to final review): signIn is duplicated ~6 times inline
  across auth.spec.js rather than shared — verbatim brief content, and
  spec-file self-containment is a defensible Playwright convention.
Task 12: Minor (deferred to final review): §3/§9 use `- **bold**` bullets where
  surrounding invariants use bare `**bold**` paragraphs (implementer flagged
  this transparently rather than silently reformatting); README's Accounts
  section does not mention the loopback-only constraint, which is exactly the
  fact an operator needs before exposing the service; set-password and
  revoke-sessions are listed with no explanation of when to use them. All three
  trace to my brief's template.
