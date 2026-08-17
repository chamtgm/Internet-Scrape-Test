import json
from datetime import UTC, datetime

from sqlalchemy import func, select

from reachstore.adapters.base import NormalizedItem
from reachstore.models import Item, Source, User
from reachstore.store import upsert_items

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def make_source(session) -> Source:
    source = Source(kind="rss", identifier="https://example.com/feed", tier=1, config_json={}, created_at=NOW)
    session.add(source)
    session.flush()
    return source


def make_user(session, email: str) -> User:
    user = User(email=email, display_name=email.split("@")[0], created_at=NOW)
    session.add(user)
    session.flush()
    return user


def sample_items() -> list[NormalizedItem]:
    return [
        NormalizedItem(
            external_id="post-1",
            url="https://example.com/1",
            title="First post",
            content_text="hello world",
            published_at=NOW,
            raw={"id": "post-1"},
        ),
        NormalizedItem(
            external_id="post-2",
            url="https://example.com/2",
            title="Second post",
            content_text="goodbye world",
            published_at=NOW,
            raw={"id": "post-2"},
        ),
    ]


def test_upsert_inserts_new_items(session, raw_dir):
    source = make_source(session)
    new_count = upsert_items(
        session, source_id=source.id, items=sample_items(), owner_user_id=None, raw_dir=raw_dir, now=NOW
    )
    assert new_count == 2
    assert session.execute(select(func.count()).select_from(Item)).scalar_one() == 2


def test_upsert_is_idempotent(session, raw_dir):
    source = make_source(session)
    upsert_items(session, source_id=source.id, items=sample_items(), owner_user_id=None, raw_dir=raw_dir, now=NOW)
    second = upsert_items(
        session, source_id=source.id, items=sample_items(), owner_user_id=None, raw_dir=raw_dir, now=NOW
    )
    assert second == 0
    assert session.execute(select(func.count()).select_from(Item)).scalar_one() == 2


def test_upsert_writes_raw_payload_to_disk(session, raw_dir):
    source = make_source(session)
    upsert_items(session, source_id=source.id, items=sample_items()[:1], owner_user_id=None, raw_dir=raw_dir, now=NOW)
    item = session.execute(select(Item)).scalars().one()
    assert item.raw_path is not None
    saved = json.loads((raw_dir / item.raw_path).read_text())
    assert saved == {"id": "post-1"}


def test_upsert_records_owner_for_private_items(session, raw_dir):
    source = make_source(session)
    user = make_user(session, "a@example.com")
    upsert_items(
        session, source_id=source.id, items=sample_items(), owner_user_id=user.id, raw_dir=raw_dir, now=NOW
    )
    owners = session.execute(select(Item.owner_user_id)).scalars().all()
    assert owners == [user.id, user.id]


def test_same_external_id_different_sources_are_distinct(session, raw_dir):
    source_a = make_source(session)
    source_b = Source(kind="rss", identifier="https://other.com/feed", tier=1, config_json={}, created_at=NOW)
    session.add(source_b)
    session.flush()
    upsert_items(session, source_id=source_a.id, items=sample_items(), owner_user_id=None, raw_dir=raw_dir, now=NOW)
    upsert_items(session, source_id=source_b.id, items=sample_items(), owner_user_id=None, raw_dir=raw_dir, now=NOW)
    assert session.execute(select(func.count()).select_from(Item)).scalar_one() == 4
