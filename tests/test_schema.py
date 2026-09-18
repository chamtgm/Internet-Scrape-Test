import pytest
from sqlalchemy import text

EXPECTED_TABLES = {
    "users",
    "collectors",
    "sources",
    "subscriptions",
    "items",
    "fetch_runs",
    "item_tags",
}


def test_all_tables_exist(session):
    rows = session.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    ).scalars().all()
    assert EXPECTED_TABLES.issubset(set(rows))


def test_items_has_generated_tsvector_column(session):
    row = session.execute(
        text(
            "SELECT is_generated FROM information_schema.columns "
            "WHERE table_name = 'items' AND column_name = 'content_tsv'"
        )
    ).scalar_one()
    assert row == "ALWAYS"


def test_tsvector_index_exists(session):
    names = session.execute(
        text("SELECT indexname FROM pg_indexes WHERE tablename = 'items'")
    ).scalars().all()
    assert "items_content_tsv_idx" in names


def test_auth_tables_exist_with_expected_columns(session):
    from sqlalchemy import inspect

    insp = inspect(session.get_bind())
    assert "sessions" in insp.get_table_names()
    assert "invites" in insp.get_table_names()

    session_cols = {c["name"] for c in insp.get_columns("sessions")}
    assert session_cols == {"id", "user_id", "token_hash", "created_at", "expires_at"}

    invite_cols = {c["name"] for c in insp.get_columns("invites")}
    assert invite_cols == {
        "id", "email", "display_name", "is_admin",
        "token_hash", "created_at", "expires_at", "consumed_at",
    }

    user_cols = {c["name"] for c in insp.get_columns("users")}
    assert "is_admin" in user_cols


def test_session_token_hash_is_unique(session):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy.exc import IntegrityError

    from reachstore.models import User, UserSession

    now = datetime(2026, 9, 18, tzinfo=UTC)
    user = User(email="dup@example.test", display_name="Dup", created_at=now)
    session.add(user)
    session.flush()

    for _ in range(2):
        session.add(
            UserSession(
                user_id=user.id,
                token_hash="a" * 64,
                created_at=now,
                expires_at=now + timedelta(days=30),
            )
        )
    with pytest.raises(IntegrityError):
        session.flush()


def test_deleting_a_user_deletes_their_sessions(session):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, select

    from reachstore.models import User, UserSession

    now = datetime(2026, 9, 18, tzinfo=UTC)
    user = User(email="cascade@example.test", display_name="Cascade", created_at=now)
    session.add(user)
    session.flush()
    session.add(
        UserSession(
            user_id=user.id,
            token_hash="b" * 64,
            created_at=now,
            expires_at=now + timedelta(days=30),
        )
    )
    session.flush()

    session.delete(user)
    session.flush()
    remaining = session.execute(select(func.count(UserSession.id))).scalar()
    assert remaining == 0
