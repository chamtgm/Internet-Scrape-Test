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


def test_search_kinds_and_subscribed_only_combine_with_and(session, raw_dir):
    # Alice is subscribed to the shared `rss` source but not to the `x_account`
    # source, even though her own private item lives there and is normally
    # visible to her. This proves the two joins are ANDed, not one silently
    # overriding the other.
    alice, bob = setup_two_users_with_private_items(session, raw_dir)

    rss_subscribed = {
        item.title
        for item in search(session, user_id=alice.id, q="alpha", kinds=["rss"], subscribed_only=True)
    }
    assert rss_subscribed == {"public news"}

    x_account_subscribed = search(
        session, user_id=alice.id, q="alpha", kinds=["x_account"], subscribed_only=True
    )
    assert x_account_subscribed == []


def setup_items_for_pagination(session, raw_dir):
    alice = User(email="alice-page@example.com", display_name="alice-page", created_at=NOW)
    bob = User(email="bob-page@example.com", display_name="bob-page", created_at=NOW)
    session.add_all([alice, bob])
    session.flush()

    source = Source(kind="rss", identifier="https://pagination.example.com/feed", tier=1, config_json={}, created_at=NOW)
    session.add(source)
    session.flush()

    def add_shared(external_id, title):
        upsert_items(
            session,
            source_id=source.id,
            items=[
                NormalizedItem(
                    external_id=external_id,
                    url=f"https://pg/{external_id}",
                    title=title,
                    content_text="body",
                    published_at=NOW,
                )
            ],
            owner_user_id=None,
            raw_dir=raw_dir,
            now=NOW,
        )

    # Three shared items, then Bob's private item, then two more shared items.
    # All share the same published_at, so `feed`'s tie-break (desc(Item.id))
    # determines order - which also puts Bob's private item's id squarely inside
    # the id range a before_id page would otherwise return. That makes this a
    # real test of visible_to composing correctly with before_id, not one
    # masking a bug in the other.
    add_shared("p1", "page item 1")
    add_shared("p2", "page item 2")
    add_shared("p3", "page item 3")
    upsert_items(
        session,
        source_id=source.id,
        items=[
            NormalizedItem(
                external_id="priv",
                url="https://pg/priv",
                title="bob private pagination item",
                content_text="body",
                published_at=NOW,
            )
        ],
        owner_user_id=bob.id,
        raw_dir=raw_dir,
        now=NOW,
    )
    add_shared("p4", "page item 4")
    add_shared("p5", "page item 5")
    return alice, bob


def test_feed_before_id_paginates_and_respects_isolation(session, raw_dir):
    alice, bob = setup_items_for_pagination(session, raw_dir)

    full = feed(session, user_id=alice.id)
    full_titles = [item.title for item in full]
    assert full_titles == ["page item 5", "page item 4", "page item 3", "page item 2", "page item 1"]
    assert "bob private pagination item" not in full_titles

    cursor = next(item for item in full if item.title == "page item 4")
    page = feed(session, user_id=alice.id, before_id=cursor.id)
    page_titles = [item.title for item in page]
    assert page_titles == ["page item 3", "page item 2", "page item 1"]
    assert all(item.id < cursor.id for item in page)
    assert "bob private pagination item" not in page_titles
