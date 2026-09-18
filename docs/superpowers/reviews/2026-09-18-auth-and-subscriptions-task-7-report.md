# Task 7 Report: `POST /api/auth/setup` — redeem an invite

## What I implemented

- `POST /api/auth/setup` in `src/reachstore/api/routes.py`: an unauthenticated endpoint that
  redeems a single-use invite token, creates the `User` row, logs the new account straight in
  (same cookie as login), and returns the projected user.
- Ordering: password length is checked **before** `consume_invite` is called, so a typo on
  the password never burns the single-use link.
- Status codes: a single 400 (`"invalid or expired setup link"`) for every token-related
  failure (unknown, already consumed, expired, password too short); 409
  (`"that email already has an account"`) only for the email-collision case, since the token
  holder already knows the email.
- On the 409 path, `session.commit()` still runs before raising, so the invite stays consumed
  even when account creation is rejected — no infinitely-retryable link against an existing
  account.

## Deviation from the brief's literal Step 3 code (per the task's own instructions)

The brief's inline code sample uses `session.execute(select(User).where(User.email ==
invite.email))...` and hand-builds `UserOut(...)`. The task instructions explicitly override
this: "`routes.py` currently contains no `select(`... Keep `routes.py` query-free — use the
helper for the email-collision check" and "Reuse both [`_set_session_cookie` and `_user_out`]."
I followed the instructions, not the brief's literal snippet:
- Used `find_user_by_email(session, invite.email)` instead of inlining a `select`.
- Used `_user_out(user)` instead of hand-constructing `UserOut(...)`.

Verified after implementing: `grep -n "select(" src/reachstore/api/routes.py` → no matches;
no `sqlalchemy.select`/`sqlalchemy import select` in the file. `routes.py` stays query-free.

## TDD evidence

**RED** — `.venv/bin/pytest tests/test_api_auth.py -k setup -v`

7 of the 8 new tests matched `-k setup` (the 8th, `test_the_new_account_can_log_in_afterwards`,
doesn't contain "setup" in its name, so `-k setup` didn't select it — same as the brief's
command would do). All 7 selected tests failed:

```
FAILED tests/test_api_auth.py::test_setup_creates_the_account_and_logs_it_in - assert 405 == 200
FAILED tests/test_api_auth.py::test_setup_carries_the_invited_admin_flag - KeyError: 'is_admin'
FAILED tests/test_api_auth.py::test_setup_token_works_exactly_once - AssertionError: assert 405 == 200
FAILED tests/test_api_auth.py::test_setup_rejects_an_unknown_token - assert 405 == 400
FAILED tests/test_api_auth.py::test_setup_rejects_an_expired_invite - assert 405 == 400
FAILED tests/test_api_auth.py::test_setup_rejects_a_short_password_without_consuming_the_invite - AssertionError: assert 405 == 400
FAILED tests/test_api_auth.py::test_setup_is_409_when_the_email_already_has_an_account - assert 405 == 409
======================= 7 failed, 9 deselected in 0.29s ========================
```

**Note on 405 vs. the brief's expected 404:** the brief expects a 404 for the missing route.
This repo's `web/dist` is already built (`ls web/dist` shows `index.html`, `assets/`,
`favicon.svg`), so `create_app()` mounts `StaticFiles` at `"/"` as a catch-all. A request to an
unmatched path falls through to that mount, which only permits GET/HEAD, so Starlette returns
405 instead of 404. This is an artifact of the dev environment having a built frontend, not a
flaw in the brief or the route — the tests still fail for the right underlying reason (the
route doesn't exist yet), and once the router registers `/auth/setup`, `app.include_router(router)`
(called before the static mount in `create_app()`) wins the match. I did not change anything
about this; flagging it only so the 405-vs-404 discrepancy in the raw pytest output isn't
mistaken for a bug.

**GREEN** — `.venv/bin/pytest tests/test_api_auth.py -v`

```
tests/test_api_auth.py::test_login_sets_a_cookie_and_returns_the_user PASSED
tests/test_api_auth.py::test_login_then_me_returns_the_same_user PASSED
tests/test_api_auth.py::test_me_without_a_session_is_401 PASSED
tests/test_api_auth.py::test_wrong_password_and_unknown_email_are_indistinguishable PASSED
tests/test_api_auth.py::test_login_rejects_the_empty_password_hash PASSED
tests/test_api_auth.py::test_logout_invalidates_the_session PASSED
tests/test_api_auth.py::test_logout_without_a_session_is_401 PASSED
tests/test_api_auth.py::test_admin_flag_is_reported PASSED
tests/test_api_auth.py::test_setup_creates_the_account_and_logs_it_in PASSED
tests/test_api_auth.py::test_setup_carries_the_invited_admin_flag PASSED
tests/test_api_auth.py::test_the_new_account_can_log_in_afterwards PASSED
tests/test_api_auth.py::test_setup_token_works_exactly_once PASSED
tests/test_api_auth.py::test_setup_rejects_an_unknown_token PASSED
tests/test_api_auth.py::test_setup_rejects_an_expired_invite PASSED
tests/test_api_auth.py::test_setup_rejects_a_short_password_without_consuming_the_invite PASSED
tests/test_api_auth.py::test_setup_is_409_when_the_email_already_has_an_account PASSED
============================== 16 passed in 0.98s ==============================
```

16 passed (8 from Task 4 + 8 new here), matching the brief's expectation exactly.

## Files changed

- `src/reachstore/api/routes.py` — extended the `auth` import with `MIN_PASSWORD_LENGTH`,
  `consume_invite`, `hash_password`; extended the schemas import with `SetupRequest`; added
  `post_setup`.
- `tests/test_api_auth.py` — added top-level imports (`datetime`, `UTC`, `timedelta`, and
  `reachstore.api.auth` as `auth`), appended the 8 setup tests and the `_invite` helper from
  the brief.

## Step 5 — redeem the real invite against the dev database

Port 8000 was already held by an unrelated `php` process (PID 29601) — left untouched per the
hard rule. Started the API on port 8100 instead:

```
.venv/bin/python -c "import uvicorn; from reachstore.api.app import create_app; uvicorn.run(create_app(), host='127.0.0.1', port=8100)"
```
PID 54029 (backgrounded, logged to `/tmp/reachstore_server_8100.log`). Confirmed startup via
the log (`Uvicorn running on http://127.0.0.1:8100`).

Redeemed the invite:

```
curl -s -i -X POST http://127.0.0.1:8100/api/auth/setup \
  -H 'Content-Type: application/json' \
  -d '{"token":"bkSH_0e_Uxh5jz7_A219cbxNvTwSRH1-hwxUOXZzP1Q","password":"Reachstore-Setup-2026!"}'
```

Response:

```
HTTP/1.1 200 OK
content-type: application/json
set-cookie: reachstore_session=cWWJxunMRAzTvWilzegzbk1fOHKBheuWdT0o4brAPCM; HttpOnly; Max-Age=2592000; Path=/; SameSite=lax

{"id":2,"email":"you@example.com","display_name":"You","is_admin":true}
```

`is_admin: true` confirmed, as required.

**Password set for `you@example.com`: `Reachstore-Setup-2026!`** — Tasks 9–11 need this to log
in by hand.

Stopped the server afterward: `kill 54029`, verified with `ps -p 54029` (no such process) and
confirmed port 8100 was free again. No other process was touched.

The invite token has now been consumed (this endpoint works exactly once, verified by the
suite's `test_setup_token_works_exactly_once`). If a fresh token is needed for later manual
testing, re-mint with:
```
.venv/bin/python -m reachstore.cli invite you@example.com --name "You" --admin
```

## Confirmation of reuse discipline

- `_set_session_cookie(response, token)` — reused unchanged, the one place the cookie is
  written. No second `set_cookie` call added.
- `_user_out(user)` — reused unchanged, the one place a `User` is projected to `UserOut`.
- `SetupRequest` — imported from `schemas.py`, not redefined.
- `find_user_by_email` — reused for the email-collision check instead of inlining a query, per
  the task's explicit override of the brief's literal code.
- `routes.py` builds no SQL — confirmed via grep, no `select(` anywhere in the file.

## COOKIE_NAME import style

Kept the file internally consistent with the **bare `COOKIE_NAME` import** that Task 4's tests
already used (`from reachstore.api.auth import COOKIE_NAME`, referenced as plain `COOKIE_NAME`).
Added `from reachstore.api import auth` alongside it for `auth.create_invite` and
`auth.INVITE_LIFETIME`, but changed the brief's `auth.COOKIE_NAME` reference in the new setup
test to the bare `COOKIE_NAME` already in scope, rather than introducing a second style for the
same name in one file.

## Full suite

`.venv/bin/pytest` → **187 passed** (179 baseline + 8 new), 0 warnings, ~4.5s. Suite count did
not drop, and stayed warning-free.

## Self-review findings

- Re-read the diff (`git diff` before commit): route logic matches the brief's intent exactly,
  with the two deliberate substitutions above (helper reuse, no inline `select`/`UserOut`).
- Confirmed `now = datetime.now(UTC)` is read once in the handler (entrypoint) and threaded
  into `consume_invite`, `create_session`, and the new `User.created_at` — no second clock read,
  no real-clock read inside `auth.py`.
- Confirmed the 409 path commits before raising (`session.commit()` then `raise HTTPException`),
  matching the "invite is spent either way" requirement.
- Confirmed the password-length check runs strictly before `consume_invite` is called.
- No new dependencies, no CORS changes, no edits under `docs/superpowers/specs|plans|reviews/`.
- `ruff` is not installed in this venv (`.venv/bin/ruff` → not found), so no lint pass was run;
  nothing else in the repo's task instructions calls for it and the test suite doesn't gate on it.

## Concerns

None blocking. Two things worth flagging for the record:

1. The 405-vs-404 discrepancy in Step 2 (explained above) — purely an artifact of `web/dist`
   being built in this workspace; not a defect.
2. Port 8000 was occupied by an unrelated process this task correctly avoided — worth
   mentioning in case Tasks 9–11's manual testing instructions assume port 8000 is free; it
   currently is not (still held by PID 29601, a `php` process, untouched by this task).
