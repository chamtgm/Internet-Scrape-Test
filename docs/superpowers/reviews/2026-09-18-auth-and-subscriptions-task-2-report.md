# Task 2 Report: `api/auth.py` — passwords, sessions, invites

## Status: DONE

## What was implemented

`src/reachstore/api/auth.py`, created exactly as specified in the task brief:

- **Constants:** `COOKIE_NAME = "reachstore_session"`, `SESSION_LIFETIME = timedelta(days=30)`, `INVITE_LIFETIME = timedelta(days=7)`, `MIN_PASSWORD_LENGTH = 8`.
- **Passwords:** `hash_password(password)` / `verify_password(password, encoded)` using stdlib `hashlib.scrypt` (n=2**15, r=8, p=1, dklen=64), encoded as `scrypt$n$r$p$<b64 salt>$<b64 digest>`. `verify_password` parses with the same `n`/`r`/`p` read back out of the stored hash (not the module's current constants) and derives `maxmem` from those parsed values via a `_maxmem(n, r)` helper, so raising the cost parameters later won't invalidate old hashes. Malformed/empty input is caught by `(AttributeError, ValueError, TypeError)` and returns `False` rather than raising.
- **Timing-safe comparison:** `secrets.compare_digest` for the digest check; `spend_dummy_verify()` burns one scrypt call on a cached dummy hash so an unknown-email login path costs the same as a wrong-password one.
- **Sessions:** `create_session` (returns raw token, stores only its SHA-256 digest), `lookup_session` (deletes the row on the way past expiry, so no scheduled cleanup job is needed), `delete_session` (idempotent), `delete_all_sessions` (bulk revoke, returns count).
- **Invites:** `create_invite` (raw token returned, digest stored), `consume_invite` (marks `consumed_at`, rejects unknown/expired/already-consumed tokens by returning `None`).
- **FastAPI dependencies:** `get_current_user` (401 on missing/invalid cookie; the only place in this module that calls `datetime.now(UTC)`), `require_admin` (403 if not `user.is_admin`).

No endpoints were added — this task only produces the module and its dependencies, as instructed.

## Testing

`tests/test_auth_unit.py`, created verbatim from the brief: 22 test items (18 test functions, one parametrised 5 ways) covering password round-trip, wrong-password rejection, per-password salting, malformed/empty hash handling, digest tampering, session create/lookup/expiry-boundary/delete/bulk-delete, and invite create/consume/double-consume/expiry/unknown-token/no-raw-token-stored.

### TDD evidence

**RED** — `.venv/bin/pytest tests/test_auth_unit.py -v` before `auth.py` existed:

```
ImportError while importing test module '.../tests/test_auth_unit.py'.
...
tests/test_auth_unit.py:5: in <module>
    from reachstore.api import auth
E   ImportError: cannot import name 'auth' from 'reachstore.api' (.../src/reachstore/api/__init__.py)
=========================== short test summary info ============================
ERROR tests/test_auth_unit.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```

Expected for the right reason: `reachstore/api/auth.py` did not exist yet. (Note: Python reports `ImportError: cannot import name 'auth'` rather than the brief's literal `ModuleNotFoundError: No module named 'reachstore.api.auth'`, because the test does `from reachstore.api import auth` against an existing `reachstore.api` package, not `import reachstore.api.auth`. Same root cause — module absent — different phrasing from the interpreter.)

**GREEN** — `.venv/bin/pytest tests/test_auth_unit.py -v` after implementing `auth.py`:

```
collected 22 items

tests/test_auth_unit.py::test_password_round_trip PASSED                 [  4%]
tests/test_auth_unit.py::test_wrong_password_rejected PASSED             [  9%]
tests/test_auth_unit.py::test_same_password_hashes_differently_each_time PASSED [ 13%]
tests/test_auth_unit.py::test_malformed_or_empty_hash_is_rejected_without_raising[] PASSED [ 18%]
tests/test_auth_unit.py::test_malformed_or_empty_hash_is_rejected_without_raising[not-a-hash] PASSED [ 22%]
tests/test_auth_unit.py::test_malformed_or_empty_hash_is_rejected_without_raising[scrypt$only$three$parts] PASSED [ 27%]
tests/test_auth_unit.py::test_malformed_or_empty_hash_is_rejected_without_raising[bcrypt$1$2$3$4$5] PASSED [ 31%]
tests/test_auth_unit.py::test_malformed_or_empty_hash_is_rejected_without_raising[scrypt$x$8$1$AAAA$BBBB] PASSED [ 36%]
tests/test_auth_unit.py::test_tampered_digest_rejected PASSED            [ 40%]
tests/test_auth_unit.py::test_create_then_lookup_returns_the_user PASSED [ 45%]
tests/test_auth_unit.py::test_raw_token_is_not_stored PASSED             [ 50%]
tests/test_auth_unit.py::test_unknown_token_returns_none PASSED          [ 54%]
tests/test_auth_unit.py::test_expired_session_is_rejected_and_deleted PASSED [ 59%]
tests/test_auth_unit.py::test_session_valid_right_up_to_expiry PASSED    [ 63%]
tests/test_auth_unit.py::test_delete_session_logs_out PASSED             [ 68%]
tests/test_auth_unit.py::test_delete_session_is_idempotent PASSED        [ 72%]
tests/test_auth_unit.py::test_delete_all_sessions_revokes_every_one PASSED [ 77%]
tests/test_auth_unit.py::test_invite_round_trip PASSED                   [ 81%]
tests/test_auth_unit.py::test_invite_cannot_be_consumed_twice PASSED     [ 86%]
tests/test_auth_unit.py::test_expired_invite_is_rejected PASSED          [ 90%]
tests/test_auth_unit.py::test_unknown_invite_token_is_rejected PASSED    [ 95%]
tests/test_auth_unit.py::test_invite_raw_token_is_not_stored PASSED      [100%]

============================== 22 passed in 0.60s ==============================
```

Matches the brief's expected count (22 items) exactly.

### Crypto parameter sanity check (independent of the test suite)

```
hash_password: 39.4 ms
fields: 6
verify_password: 36.9 ms
```

Confirms the brief's stated ~40 ms / 6 `$`-separated fields on this machine.

### Full suite (Step 6)

`.venv/bin/pytest` — 142 passed (120 pre-existing + 22 new), 2.14s, no warnings summary section (`grep -i warn` on the full output matched nothing).

## Files changed

- `src/reachstore/api/auth.py` (new)
- `tests/test_auth_unit.py` (new)

Commit: `bac790c feat: auth module — scrypt passwords, revocable sessions, invites`

## Step 5: constraint-boundary grep

```
$ grep -n "select(\|delete(" src/reachstore/api/auth.py
135:            select(UserSession).where(UserSession.token_hash == _digest(token))
144:        session.delete(row)
151:    session.execute(delete(UserSession).where(UserSession.token_hash == _digest(token)))
156:    result = session.execute(delete(UserSession).where(UserSession.user_id == user_id))
182:        session.execute(select(Invite).where(Invite.token_hash == _digest(token)))
```

All 5 hits reference `UserSession` or `Invite` only. No `Item`, `Source`, `FetchRun`, or `ItemTag`. The one `User` read in the module (`session.get(User, row.user_id)` in `lookup_session`) is a primary-key lookup via `Session.get`, not `select()`/`delete()`, so it doesn't appear in this grep — but it still only touches `users`, one of the three tables this module owns.

## Self-review findings

- Read the full diff (`git diff --stat` showed only the two new files, nothing unexpected touched).
- Verified `from __future__ import annotations` and type hints match the surrounding codebase's style (`deps.py`).
- Verified `datetime.now(UTC)` appears exactly once, inside `get_current_user`; every other function takes `now: datetime` as a parameter.
- Verified no new dependencies were imported — only `base64`, `hashlib`, `secrets` (stdlib) plus `fastapi`/`sqlalchemy`, both already project dependencies.
- Verified `maxmem` in `verify_password` is computed from the parsed `n_i, r_i` (not the module's current `_N`/`_R` constants), matching the brief's requirement that raising cost parameters later won't invalidate existing hashes.
- Ran `.venv/bin/python -W error -c "from reachstore.api import auth"` — imports cleanly with warnings promoted to errors, confirming no deprecation noise at import time.
- `spend_dummy_verify()` has no direct test in this task's file, matching the brief's Step 1 test file exactly (it's exercised once an endpoint calls it in Task 5 — login timing safety). Did not add an unrequested test for it, per the instruction to follow the brief precisely rather than improvise.
- No endpoints, routers, or `app.py` wiring were added — this task is module-only, as instructed.

## Concerns

None. The brief's constants, code, and test file were transcribed verbatim and all measurements (scrypt timing, field count, exception types) matched what was promised. The only deviation from the brief's literal text was the RED-step exception class (`ImportError` vs `ModuleNotFoundError`), which is an artifact of `from X import Y` vs `import X.Y` import syntax, not a sign of a wrong transcription — noted above with explanation.

---

# Fix Report: Task 2 review round (Importants 1–3, Minors 1–3)

## Status: DONE

Reviewer findings addressed: 3 Important, 3 Minor. All accepted — no pushback needed, the reasoning in each finding checked out on inspection and was confirmed by mutation testing (below). Three items deferred by the reviewer (`consume_invite` race, `rowcount` normalization, unread `MIN_PASSWORD_LENGTH`) were left untouched as instructed.

## What changed, per finding

**Important 1 — zero coverage on `get_current_user`/`require_admin`.** Added 6 tests calling both dependencies as plain functions (no FastAPI DI, no HTTP): missing cookie → 401, unknown token → 401, expired token → 401, valid token → returns the user, non-admin → `require_admin` raises 403, admin → `require_admin` returns the user.

**Important 2 — expired-session cleanup never persists.** Confirmed the premise: `deps.get_session` (`src/reachstore/api/deps.py:40-46`) only `close()`s, never commits, so the `DELETE` issued on the expiry branch of `lookup_session` was flushed and discarded on every read-only request. Removed the deletion entirely per the reviewer's explicit direction (not "commit instead" — a GET must not write, and committing would also commit unrelated pending work in the request-scoped session). `lookup_session` is now a pure read: `if row is None or row.expires_at <= now: return None`. Rewrote the docstring to state the true behavior and why it's fine (a handful of users, 30-day sessions — negligible row growth; reclaiming is a separate concern if it ever matters).

Updated `tests/test_auth_unit.py::test_expired_session_is_rejected_and_deleted` (renamed to `test_expired_session_is_rejected`) since its old assertion (`count == 0`, i.e. the row was deleted) is no longer true — it now asserts the row is inert but still present (`count == 1`).

**Important 3 — `except` was swallowing real crypto faults.** In `verify_password`, moved the `hashlib.scrypt(...)` call outside the `try` block; the `try` now covers only `encoded.split("$")`, the tuple unpack, `int()` parsing, and both `base64.b64decode` calls. A genuine scrypt-parameter fault (e.g. `maxmem` wrong for a future raised cost setting) now raises instead of returning `False`. Verified none of the 5 parametrised malformed-hash test cases reach the `scrypt()` call (all fail during parsing), so `test_malformed_or_empty_hash_is_rejected_without_raising` behavior is unchanged.

**Minor 1 — `spend_dummy_verify` double-cost on first call.** Added `return` right after `_DUMMY = hash_password(...)` on the populate branch, so the first call costs one scrypt op (matching every later call, which costs one `verify_password` op), not two. Added `test_spend_dummy_verify_does_not_raise`, calling it twice to exercise both branches.

**Minor 2 — cookie parameter name as an implicit contract.** Changed `get_current_user`'s signature to `token: str | None = Cookie(default=None, alias=COOKIE_NAME)`. Renamed the parameter from `reachstore_session` to `token` (rather than keeping the old name and only adding `alias=`) to make the point concrete: the parameter's *name* is now irrelevant to cookie binding, only `alias=COOKIE_NAME` matters. Verified no other file in the repo references the old parameter name (`grep -rn "reachstore_session" --include="*.py"` only matches the `COOKIE_NAME` constant and its own docstring) — safe, since no endpoint wires this dependency yet (Task 5).

Note: `docs/superpowers/plans/2026-09-18-auth-and-subscriptions.md` was updated in a prior commit (`d26a9ee`, plan-doc only, no source changes) with a reference snippet that keeps the parameter named `reachstore_session` and only adds the alias. My implementation applies the same fix (alias-based binding) but renames the parameter to `token`; functionally identical, cosmetically different from that doc's snippet. Flagging for awareness, not fixing — out of this task's scope to edit the plan document.

**Minor 3 — no test pinned the exact expiry instant.** Added `test_session_expired_at_the_exact_instant` (`now = NOW + SESSION_LIFETIME`) and `test_invite_expired_at_the_exact_instant` (`now = NOW + INVITE_LIFETIME`), both asserting `None`/rejection.

## Mutation testing (evidence the new tests catch real regressions)

Each mutation was applied to a scratch copy of `auth.py`, the targeted tests run, then immediately reverted (confirmed via `diff` against a pre-mutation backup — file byte-identical afterward).

1. **Inverted `require_admin`'s check** (`if not user.is_admin` → `if user.is_admin`):
   ```
   FAILED tests/test_auth_unit.py::test_require_admin_rejects_non_admin - Failed: DID NOT RAISE HTTPException
   FAILED tests/test_auth_unit.py::test_require_admin_allows_admin - fastapi.exceptions.HTTPException: 403: admin only
   ```
   Both new `require_admin` tests catch it.

2. **Expiry boundary regressed from `<=` to `<`** in `lookup_session`:
   ```
   FAILED tests/test_auth_unit.py::test_session_expired_at_the_exact_instant - AssertionError: assert <reachstore.models.User object ...> is None
   ```
   The exact-instant test catches it; the pre-existing `±1s` tests (`test_expired_session_is_rejected`, `test_session_valid_right_up_to_expiry`) still passed under the same mutation — confirming they genuinely could not have caught this regression, which is exactly the gap Minor 3 identified.

3. **Simulated a real scrypt fault** (non-power-of-2 `n` in an otherwise well-formed hash, standing in for "maxmem wrong for a raised cost setting"):
   ```
   ValueError propagated as expected: n must be a power of 2.
   ```
   Confirms Important 3's fix: the fault now surfaces instead of returning `False`.

## Test commands and output

Focused run:
```
$ .venv/bin/pytest tests/test_auth_unit.py -v
...
collected 31 items
...
============================== 31 passed in 0.70s ==============================
```
(22 pre-existing + 9 new: 1 `spend_dummy_verify`, 2 exact-boundary, 4 `get_current_user`, 2 `require_admin`.)

Full suite:
```
$ .venv/bin/pytest
...
============================= 151 passed in 2.25s ==============================
```
(120 baseline + 31 auth tests.) `grep -i warn` on the full output matched nothing — no warnings summary section, output pristine.

## Step 5 re-check (constraint boundary, after the fix round)

```
$ grep -n "select(\|delete(" src/reachstore/api/auth.py
155:            select(UserSession).where(UserSession.token_hash == _digest(token))
166:    session.execute(delete(UserSession).where(UserSession.token_hash == _digest(token)))
171:    result = session.execute(delete(UserSession).where(UserSession.user_id == user_id))
197:        session.execute(select(Invite).where(Invite.token_hash == _digest(token)))
```
Unchanged: still only `UserSession` and `Invite`. No `Item`, `Source`, `FetchRun`, or `ItemTag`.

## Files changed (this round)

- `src/reachstore/api/auth.py`
- `tests/test_auth_unit.py`

Commit: `c4938ed fix: auth review round — dependency coverage, no phantom cleanup, scrypt faults surface`

## Concerns

None outstanding. The one thing worth flagging (not a concern, just noted above): the cookie parameter's name (`token`) differs cosmetically from the plan document's reference snippet (`reachstore_session` + alias) — both are correct fixes for the same footgun, I chose the name that makes the decoupling from `COOKIE_NAME` explicit.
