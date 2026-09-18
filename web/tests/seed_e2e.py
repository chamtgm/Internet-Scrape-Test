"""Seed the TEST database with deterministic data for the Playwright smoke test.

Run from the repo root:  .venv/bin/python web/tests/seed_e2e.py

Idempotent -- `upsert_items` conflicts on (source_id, external_id) and skips,
so re-running adds nothing. It also resets the seeded user's subscriptions to
unsubscribed on every run: `unsubscribe` is a soft delete that only clears
`active` (see store.py), so without this reset a second `npm run test:e2e`
would start with a subscription already in place and fail the "nothing
subscribed" precondition. Safe to run before every e2e invocation.

Note: pytest's `engine` fixture runs DROP SCHEMA on this same database at
session scope, so do not run the Python suite and the e2e suite concurrently.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select, update

from reachstore.adapters.base import NormalizedItem
from reachstore.api.auth import hash_password
from reachstore.config import get_settings
from reachstore.db import make_engine, make_session_factory
from reachstore.models import Source, Subscription, User
from reachstore.store import upsert_items

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
COUNT = 12
RAW_DIR = Path("data/raw-e2e")

# Credentials for the Playwright specs. Plain text on purpose: this account
# exists only in the *_test database, which pytest's engine fixture drops at
# the start of every run.
E2E_EMAIL = "e2e-admin@example.test"
E2E_PASSWORD = "e2e-password-1234"


def main() -> None:
    settings = get_settings()
    url = settings.test_database_url
    # Same two guards as conftest.py's _guard_test_database: never touch a
    # database that is not clearly the test one. This script migrates and
    # writes; pointing it at the development database would be destructive.
    if not url or not url.endswith("_test"):
        raise SystemExit("TEST_DATABASE_URL must be set and end in '_test'. Refusing to seed.")
    if url == settings.database_url:
        raise SystemExit("TEST_DATABASE_URL must differ from DATABASE_URL. Refusing to seed.")

    os.environ["ALEMBIC_DATABASE_URL"] = url
    command.upgrade(Config("alembic.ini"), "head")

    session = make_session_factory(make_engine(url))()
    try:
        source = session.execute(
            select(Source).where(
                Source.kind == "rss", Source.identifier == "https://e2e/feed"
            )
        ).scalars().one_or_none()
        if source is None:
            source = Source(
                kind="rss",
                identifier="https://e2e/feed",
                tier=1,
                config_json={},
                created_at=NOW,
            )
            session.add(source)
            session.flush()

        user = session.execute(
            select(User).where(User.email == E2E_EMAIL)
        ).scalars().one_or_none()
        if user is None:
            user = User(
                email=E2E_EMAIL,
                display_name="E2E Admin",
                password_hash=hash_password(E2E_PASSWORD),
                is_admin=True,
                created_at=NOW,
            )
            session.add(user)
            session.flush()

        # auth.spec.js's subscription test asserts "nothing subscribed" as its
        # starting state. subscribe()/unsubscribe() only ever flip `active`
        # (never delete the row -- see store.py), so a subscription made by a
        # previous run of this same script would otherwise survive into the
        # next one and break that precondition. Reset scoped to this one
        # seeded user, matching this file's stated "safe to run before every
        # e2e invocation" contract.
        session.execute(
            update(Subscription).where(Subscription.user_id == user.id).values(active=False)
        )

        items = [
            NormalizedItem(
                external_id=f"e2e-{i}",
                url=f"https://e2e/{i}",
                title=f"Smoke test article {i}",
                content_text=(
                    f"Article {i} about collecting and searching. "
                    + "This paragraph exists so the detail pane has real length. " * 6
                ),
                published_at=NOW - timedelta(days=i),
            )
            for i in range(COUNT)
        ]
        new = upsert_items(
            session,
            source_id=source.id,
            items=items,
            owner_user_id=None,
            raw_dir=RAW_DIR,
            now=NOW,
        )
        session.commit()
        print(f"seeded {COUNT} items ({new} new) and admin {E2E_EMAIL} into {url.rsplit('/', 1)[-1]}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
