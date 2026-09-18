# Task 6 Report: CLI — invite, set-password, revoke-sessions

## What I implemented

1. `Settings.web_base_url: str = "http://127.0.0.1:5173"` in `src/reachstore/config.py`.
2. A `WEB_BASE_URL=http://127.0.0.1:5173` line (with comment) appended to `.env.example`.
3. Three Typer commands appended to `src/reachstore/cli.py`:
   - `invite EMAIL --name NAME [--admin]` — rejects a duplicate email, otherwise creates an invite and prints `<web_base_url>/#setup=<token>` as a URL fragment.
   - `set-password EMAIL` — prompts twice with hidden input (`confirmation_prompt=True`), enforces `MIN_PASSWORD_LENGTH`, rejects an unknown email.
   - `revoke-sessions EMAIL` — deletes all sessions for the account and reports the count.
4. `tests/test_cli_auth.py` — the 8 tests from the brief, copied verbatim.

## Design choice: `find_user_by_email` over inline `select(User)`

The brief's Step 4 code sample used `session.execute(select(User).where(User.email == email)).scalars().one_or_none()` inline in three places, but flagged in its own closing note that using `auth.find_user_by_email` in all three spots (matching what `post_login` already does in `api/routes.py`) is the cleaner shape. The task dispatch context reinforced this explicitly ("USE THIS... it keeps the `users` table owned by one module").

I used `find_user_by_email` in all three commands. Consequences:
- No `from sqlalchemy import select` import needed in `cli.py`.
- No `User` import needed in `cli.py` (the `from reachstore.models import Source` line is untouched).
- `cli.py` contains zero SQL against `users`, matching the "one owning module" constraint (`auth.py` owns `users`/`sessions`/`invites`).

This differs from the brief's literal code sample but was explicitly sanctioned by the brief's own footnote and the dispatch context, so I did not treat it as a deviation requiring a stop-and-ask.

## TDD evidence

**RED** — `.venv/bin/pytest tests/test_cli_auth.py -v`, before touching `cli.py`/`config.py`:

```
FAILED tests/test_cli_auth.py::test_invite_prints_a_setup_url - assert 2 == 0
 +  where 2 = <Result SystemExit(2)>.exit_code
FAILED tests/test_cli_auth.py::test_invite_admin_flag_is_recorded - assert 2 == 0
FAILED tests/test_cli_auth.py::test_invite_does_not_print_the_raw_token_twice - IndexError: list index out of range
FAILED tests/test_cli_auth.py::test_invite_rejects_a_duplicate_email - assert 2 == 1
FAILED tests/test_cli_auth.py::test_set_password_lets_the_user_log_in - assert 2 == 0
FAILED tests/test_cli_auth.py::test_set_password_rejects_a_short_password - assert 2 == 1
FAILED tests/test_cli_auth.py::test_set_password_on_an_unknown_email_exits_1 - assert 2 == 1
FAILED tests/test_cli_auth.py::test_revoke_sessions_deletes_them_and_reports_the_count - assert 2 == 0
======================== 8 failed in 0.33s ========================
```

All eight fail with Typer's `SystemExit(2)` — "no such command" — exactly as the brief predicted (`invite`/`set-password`/`revoke-sessions` did not exist yet). The one test asserting a string split (`test_invite_does_not_print_the_raw_token_twice`) fails with `IndexError` instead, because there is no `#setup=` in the Typer usage-error output to split on — same root cause, different surface symptom.

**GREEN** — `.venv/bin/pytest tests/test_cli_auth.py -v`, after implementation:

```
tests/test_cli_auth.py::test_invite_prints_a_setup_url PASSED               [ 12%]
tests/test_cli_auth.py::test_invite_admin_flag_is_recorded PASSED           [ 25%]
tests/test_cli_auth.py::test_invite_does_not_print_the_raw_token_twice PASSED [ 37%]
tests/test_cli_auth.py::test_invite_rejects_a_duplicate_email PASSED        [ 50%]
tests/test_cli_auth.py::test_set_password_lets_the_user_log_in PASSED       [ 62%]
tests/test_cli_auth.py::test_set_password_rejects_a_short_password PASSED   [ 75%]
tests/test_cli_auth.py::test_set_password_on_an_unknown_email_exits_1 PASSED [ 87%]
tests/test_cli_auth.py::test_revoke_sessions_deletes_them_and_reports_the_count PASSED [100%]
======================== 8 passed in 0.33s ========================
```

**Full suite** — `.venv/bin/pytest`:

```
======================== 179 passed in 4.20s ========================
```

171 (baseline) + 8 (new) = 179. No warnings in the output (checked explicitly with `grep -i warning`, no matches).

## Step 6: real admin account created

Ran against the development database (`.env`'s `DATABASE_URL`, port 5433):

```
$ .venv/bin/python -m reachstore.cli invite you@example.com --name "You" --admin
Invite for you@example.com (admin), valid 7 days.
http://127.0.0.1:5173/#setup=bkSH_0e_Uxh5jz7_A219cbxNvTwSRH1-hwxUOXZzP1Q
The link works once. Re-run this command to issue another.
```

**Setup URL for Task 7 (works exactly once, expires in 7 days from 2026-09-19):**

```
http://127.0.0.1:5173/#setup=bkSH_0e_Uxh5jz7_A219cbxNvTwSRH1-hwxUOXZzP1Q
```

Token: `bkSH_0e_Uxh5jz7_A219cbxNvTwSRH1-hwxUOXZzP1Q`

## Files changed

- `src/reachstore/cli.py` — added `api.auth` import block, three new commands.
- `src/reachstore/config.py` — added `web_base_url` setting.
- `.env.example` — added `WEB_BASE_URL` line and comment.
- `tests/test_cli_auth.py` — new file, 8 tests, copied verbatim from the brief.
- `.env` — untouched, not staged, not committed (verified with `git status` before commit).

## Commit

```
e025355 feat: invite, set-password, and revoke-sessions CLI commands
```

4 files changed, 255 insertions(+). No deletions — purely additive to existing files plus one new test file.

## Self-review findings

- **Completeness**: all three commands present, `web_base_url` setting present, `.env.example` line present, real admin account created against dev DB, full suite run before commit.
- **Discipline**: confirmed zero occurrences of `select(User` or raw SQL against `users`/`sessions`/`invites` in `cli.py` — every lookup goes through `auth.find_user_by_email` / `auth.create_invite` / `auth.delete_all_sessions` / `auth.hash_password`. `cli.py`'s existing `from reachstore.models import Source` line was left untouched since `User` is no longer needed there.
- **No scope creep**: did not touch `docs/superpowers/{specs,plans,reviews}/`. Did not add a `select` or `User` import that the brief's own footnote said was avoidable. Did not add any dependency.
- **Testing hygiene**: read the full final `cli.py` after editing to check for unused imports and structural consistency with the existing `add-source`/`collect`/`search`/`health` commands (same `_session()`/try-finally/`typer.echo` style) — consistent.
- **`.env` safety**: verified via `git status` immediately before `git add` that `.env` was never staged.

## Concerns

None. The brief was accurate throughout, including the RED-failure prediction and the prompt-twice behavior for `set-password`. The only judgment call — `find_user_by_email` vs. inline `select(User)` — was explicitly pre-approved by the brief's own text, so I did not stop to ask.
