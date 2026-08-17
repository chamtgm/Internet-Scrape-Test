from datetime import UTC, datetime

from reachstore.adapters.base import NormalizedItem
from reachstore.models import Source, Subscription, User
from reachstore.query import feed, get_item, search
from reachstore.store import upsert_items

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def setup_two_users_with_private_items(session, raw_dir):
    alice = User(email="alice@example.com", display_name="alice", created_at=NOW)
    bob = User(email="bob@example.com", display_name="bob", created_at=NOW)
    session.add_all([alice, bob])
    session.flush()

    source = Source(kind="x_account", identifier="@someone", tier=2, config_json={}, created_at=NOW)
    shared = Source(kind="rss", identifier="https://example.com/feed", tier=1, config_json={}, created_at=NOW)
    session.add_all([source, shared])
    session.flush()

    upsert_items(
        session,
        source_id=source.id,
        items=[NormalizedItem(external_id="a1", url="https://x/1", title="alice secret", content_text="alpha")],
        owner_user_id=alice.id,
        raw_dir=raw_dir,
        now=NOW,
    )
    upsert_items(
        session,
        source_id=shared.id,
        items=[NormalizedItem(external_id="b1", url="https://x/2", title="bob secret", content_text="alpha")],
        owner_user_id=bob.id,
        raw_dir=raw_dir,
        now=NOW,
    )
    upsert_items(
        session,
        source_id=shared.id,
        items=[NormalizedItem(external_id="s1", url="https://x/3", title="public news", content_text="alpha")],
        owner_user_id=None,
        raw_dir=raw_dir,
        now=NOW,
    )
    session.add(Subscription(user_id=alice.id, source_id=shared.id, active=True, created_at=NOW))
    session.flush()
    return alice, bob


def test_feed_excludes_other_users_private_items(session, raw_dir):
    alice, bob = setup_two_users_with_private_items(session, raw_dir)
    titles = {item.title for item in feed(session, user_id=alice.id)}
    assert "alice secret" in titles
    assert "public news" in titles
    assert "bob secret" not in titles


def test_search_excludes_other_users_private_items(session, raw_dir):
    alice, bob = setup_two_users_with_private_items(session, raw_dir)
    titles = {item.title for item in search(session, user_id=alice.id, q="alpha")}
    assert titles == {"alice secret", "public news"}


def test_get_item_refuses_other_users_private_item(session, raw_dir):
    alice, bob = setup_two_users_with_private_items(session, raw_dir)
    bobs_item = next(i for i in feed(session, user_id=bob.id) if i.title == "bob secret")
    assert get_item(session, user_id=alice.id, item_id=bobs_item.id) is None
    assert get_item(session, user_id=bob.id, item_id=bobs_item.id) is not None


def test_subscribed_only_limits_to_subscribed_sources(session, raw_dir):
    alice, bob = setup_two_users_with_private_items(session, raw_dir)
    titles = {item.title for item in search(session, user_id=alice.id, q="alpha", subscribed_only=True)}
    assert titles == {"public news"}
