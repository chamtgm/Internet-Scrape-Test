# Task 1 Report: Schema — `is_admin`, `sessions`, `invites`

## Status: DONE

## What I implemented

Followed the brief verbatim, in its TDD step order.

1. **`tests/test_schema.py`** — added `import pytest` (was missing) and appended the three tests from the brief exactly as written: `test_auth_tables_exist_with_expected_columns`, `test_session_token_hash_is_unique`, `test_deleting_a_user_deletes_their_sessions`.
2. **`src/reachstore/models.py`**
   - Added `is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))` to `class User`, immediately after `password_hash` (before `llm_provider`), per the brief.
   - Appended two new model classes at the end of the file: `UserSession` (table `sessions`) and `Invite` (table `invites`), copied verbatim from the brief, including their docstrings.
   - No new imports were added — every name used (`BigInteger`, `Boolean`, `DateTime`, `ForeignKey`, `String`, `text`, `Mapped`, `mapped_column`, `datetime`) was already imported at the top of the file.
3. **`migrations/versions/0002_auth.py`** — created new, content copied verbatim from the brief: revision `"0002"`, `down_revision = "0001"`, `upgrade()` adds `users.is_admin` (NOT NULL, server default false) and creates `sessions` and `invites` tables with the exact column specs from the brief; `downgrade()` reverses in the opposite order.

## TDD evidence

**RED** — `.venv/bin/pytest tests/test_schema.py -k "auth_tables or token_hash or cascade" -v`

The brief's `-k` filter only matched 2 of the 3 new tests (the third test is named `test_deleting_a_user_deletes_their_sessions`, which doesn't literally contain the substring "cascade" — a minor imprecision in the brief's example command, not a real problem). Output:

```
tests/test_schema.py::test_auth_tables_exist_with_expected_columns FAILED
tests/test_schema.py::test_session_token_hash_is_unique FAILED

FAILED tests/test_schema.py::test_auth_tables_exist_with_expected_columns
  AssertionError: assert 'sessions' in ['alembic_version', 'users', 'collectors',
  'subscriptions', 'sources', 'items', 'fetch_runs', 'item_tags']
FAILED tests/test_schema.py::test_session_token_hash_is_unique
  ImportError: cannot import name 'UserSession' from 'reachstore.models'
2 failed, 4 deselected in 0.17s
```

I separately confirmed the third new test also fails for the same reason:

```
$ .venv/bin/pytest tests/test_schema.py::test_deleting_a_user_deletes_their_sessions -v
FAILED tests/test_schema.py::test_deleting_a_user_deletes_their_sessions
  ImportError: cannot import name 'UserSession' from 'reachstore.models'
1 failed in 0.12s
```

Both failure modes are exactly what the brief predicted: `sessions` missing from the table list, and `ImportError` on `UserSession`.

**GREEN** — `.venv/bin/pytest tests/test_schema.py -v`

```
tests/test_schema.py::test_all_tables_exist PASSED
tests/test_schema.py::test_items_has_generated_tsvector_column PASSED
tests/test_schema.py::test_tsvector_index_exists PASSED
tests/test_schema.py::test_auth_tables_exist_with_expected_columns PASSED
tests/test_schema.py::test_session_token_hash_is_unique PASSED
tests/test_schema.py::test_deleting_a_user_deletes_their_sessions PASSED
6 passed in 0.13s
```

## Step 6: applied migration to the development database

`migrations/env.py` reads `DATABASE_URL` directly from `os.environ` (no dotenv loading), so I exported it from `.env` for the alembic invocations only (never printed or committed).

```
$ .venv/bin/alembic current
0001
$ .venv/bin/alembic upgrade head
$ .venv/bin/alembic current
0002 (head)
```

## Step 7: verification of the pre-existing user row

```
$ .venv/bin/python -c "
from sqlalchemy import select
from reachstore.config import get_settings
from reachstore.db import make_engine, make_session_factory
from reachstore.models import User
s = make_session_factory(make_engine(get_settings().database_url))()
for u in s.execute(select(User)).scalars():
    print(u.id, u.email, 'is_admin =', u.is_admin, '| empty password =', u.password_hash == '')
s.close()"

1 hand-verify@example.com is_admin = False | empty password = True
```

Matches expectation exactly: the one pre-existing row survived the migration, `is_admin` defaulted to `False` via the server default, and `password_hash` is still empty (still unable to log in once Task 2's `verify_password` rejects empty hashes).

## Step 8: full suite

```
$ .venv/bin/pytest
119 passed in 1.71s
```

116 baseline + 3 new = 119. No warnings summary printed — output is pristine, matching the "warnings are findings" constraint. (I initially tried `-W error` as an extra check; that surfaced a pre-existing, unrelated `StarletteDeprecationWarning` about `httpx`/`httpx2` at *collection* time for three unrelated API test files — not something introduced by this change, and not part of the brief's specified command, so I did not chase it and instead ran plain `pytest` as directed.)

## Files changed

- `src/reachstore/models.py` — added `User.is_admin`, `UserSession`, `Invite` (47 lines added)
- `migrations/versions/0002_auth.py` — new file, migration `0002` (50 lines)
- `tests/test_schema.py` — added `import pytest` + 3 new tests (73 lines added)

## Commit

```
80ac9a6 feat: schema for auth — users.is_admin, sessions, invites
 3 files changed, 170 insertions(+)
 create mode 100644 migrations/versions/0002_auth.py
```

## Self-review

- Diffed `src/reachstore/models.py` against the brief's code block: matches, including docstrings and comment placement.
- Diffed `migrations/versions/0002_auth.py` against the brief's code block: identical apart from the markdown fences.
- Confirmed no imports were added to `models.py` (checked the import block is untouched).
- Confirmed `is_admin` on `User` has both `default=False` and `server_default=text("false"))`, and the migration column has `nullable=False, server_default=sa.false()` — both halves of the "why both defaults" requirement are present and consistent.
- Confirmed `Invite.is_admin` intentionally has only a Python-side `default=False` (no `server_default`) in the model, matching the brief's model code — while the migration's `invites.is_admin` column does carry `server_default=sa.false()` (also per the brief, verbatim). This asymmetry is what the brief specifies, not an oversight.
- Confirmed `git status` is clean after commit, `.env` was never staged or committed, and the branch touched is the one already checked out (`feat/auth-and-subscriptions`) — I did not create or switch branches.
- Confirmed the commit contains exactly the three files listed in the brief's Step 8 — no stray files.
- Re-ran the full suite once after all changes; 119/119 passing, no warnings.

## Concerns

None. The task was self-contained schema work with an exact spec; every step matched expectations. The one deviation from literal brief text — the `-k` filter in Step 2 not catching the cascade test by name — is cosmetic (I verified that test's failure separately) and doesn't reflect anything wrong with the implementation.

---

# Fix Report: `Invite.is_admin` model/migration parity (post-review)

## Finding addressed

Review flagged that `src/reachstore/models.py`'s `Invite.is_admin` was declared as `mapped_column(Boolean, default=False)` with no `server_default`, while migration `0002_auth.py` creates that column with `server_default=sa.false()`. `User.is_admin` correctly carried both; `Invite.is_admin` carried only one, for the identical pattern. The brief (not my implementation) was the source — it specified the model that way — and the coordinator corrected the plan document separately.

## What I changed

**`src/reachstore/models.py`** — `Invite.is_admin` now matches `User.is_admin`'s pattern exactly:

```python
    is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
```

No other lines in `Invite` touched. The migration was left untouched, as instructed — it was already correct.

**`tests/test_schema.py`** — added one test, `test_is_admin_has_server_default_on_users_and_invites`, covering both tables in a single function as requested (no general-purpose schema-diff harness).

A note on how I built it: the coordinator asked for a DB-reflection check via `inspect(...).get_columns(...)`, in the style of the existing tests. I wrote that first, then verified it would actually catch a regression by temporarily reverting just `models.py` (`git stash push -- src/reachstore/models.py`) and re-running the new test alone. It **still passed** — because this suite's `session` fixture builds its schema purely via `alembic upgrade head` (confirmed in `tests/conftest.py`; there is no `Base.metadata.create_all()` anywhere in the test setup), so DB reflection only ever sees what the *migration* wrote, never what the *model* declares. The migration's `invites.is_admin` server default was never in question (review said "do not touch the migration — it is already correct"), so a DB-only check can't pin the model/migration parity the finding was actually about — it would pass identically whether or not the fix was applied.

To make the test meaningful, I kept the DB-level assertions (as instructed, and they're a legitimate check that the migration behaves identically for both tables) and added two more assertions reading `server_default` directly off the SQLAlchemy model's own column objects, `User.__table__.columns["is_admin"]` and `Invite.__table__.columns["is_admin"]`. This is the part that actually pins the finding: it fails if either model's `is_admin` column stops declaring a `server_default`, independent of what the migration says. I re-ran the same revert-and-check to confirm: with only `models.py` reverted, the test now fails with `AssertionError: assert None is not None` on the `Invite` column — exactly the bug that was fixed. Then restored the fix (`git stash pop`) and confirmed it passes again.

Final test:

```python
def test_is_admin_has_server_default_on_users_and_invites(session):
    from sqlalchemy import inspect

    from reachstore.models import Invite, User

    # DB-level: the migration must give both columns a real server default.
    insp = inspect(session.get_bind())
    users_is_admin = next(c for c in insp.get_columns("users") if c["name"] == "is_admin")
    invites_is_admin = next(c for c in insp.get_columns("invites") if c["name"] == "is_admin")
    assert users_is_admin["default"] is not None
    assert invites_is_admin["default"] is not None

    # Model-level: the ORM column definitions must agree with the migration,
    # or a future `alembic revision --autogenerate` would propose dropping
    # the one the model omits.
    assert User.__table__.columns["is_admin"].server_default is not None
    assert Invite.__table__.columns["is_admin"].server_default is not None
```

## Covering tests run

```
$ .venv/bin/pytest tests/test_schema.py -v
tests/test_schema.py::test_all_tables_exist PASSED
tests/test_schema.py::test_items_has_generated_tsvector_column PASSED
tests/test_schema.py::test_tsvector_index_exists PASSED
tests/test_schema.py::test_auth_tables_exist_with_expected_columns PASSED
tests/test_schema.py::test_session_token_hash_is_unique PASSED
tests/test_schema.py::test_deleting_a_user_deletes_their_sessions PASSED
tests/test_schema.py::test_is_admin_has_server_default_on_users_and_invites PASSED
7 passed in 0.12s
```

Regression proof (model fix reverted, new test alone):

```
$ git stash push -- src/reachstore/models.py
$ .venv/bin/pytest tests/test_schema.py::test_is_admin_has_server_default_on_users_and_invites -v
FAILED tests/test_schema.py::test_is_admin_has_server_default_on_users_and_invites
  AssertionError: assert None is not None
  +  where None = Column('is_admin', Boolean(), table=<invites>, nullable=False,
     default=ScalarElementColumnDefault(False)).server_default
1 failed in 0.12s
$ git stash pop   # fix restored
```

## Full suite before commit

```
$ .venv/bin/pytest
120 passed in 1.76s
```

119 (previous) + 1 new = 120. No warnings summary — output stayed pristine.

## Commit

```
1da6e16 fix: Invite.is_admin declares server_default to match migration (F-review)
 2 files changed, 22 insertions(+), 1 deletion(-)
```

## Concerns

None outstanding. Flagging one thing for the record rather than as a problem: the DB-reflection half of the new test (the part matching the coordinator's literal instruction) is, by itself, incapable of catching the class of bug this finding was about, because this suite's schema comes from Alembic migrations only, never from `Base.metadata`. I kept it (it's a legitimate, harmless check) but added the model-level assertions so the test actually does what "pins this parity, so the two booleans cannot drift apart again" asks for. Happy to drop the DB-level half if the reviewer would rather the test carry only the part that's load-bearing.
