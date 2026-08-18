from datetime import UTC, datetime, timedelta

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

    def add_shared(external_id, title, published_at):
        upsert_items(
            session,
            source_id=source.id,
            items=[
                NormalizedItem(
                    external_id=external_id,
                    url=f"https://pg/{external_id}",
                    title=title,
                    content_text="body",
                    published_at=published_at,
                )
            ],
            owner_user_id=None,
            raw_dir=raw_dir,
            now=NOW,
        )

    # Inserted newest-first, as adapters do: each row's id ascends while its
    # published_at descends. That is the exact condition under which a cursor
    # on `id` alone diverges from a cursor on the true sort key
    # (published_at, id) -- the two only ever coincide by accident, which a
    # tie on published_at (the old version of this fixture) guaranteed and so
    # hid the bug. Bob's private item is interleaved in the middle of the id
    # range, so this also still proves visible_to composes correctly with the
    # cursor rather than one masking a bug in the other.
    add_shared("p1", "page item 1", NOW)
    add_shared("p2", "page item 2", NOW - timedelta(hours=1))
    add_shared("p3", "page item 3", NOW - timedelta(hours=2))
    upsert_items(
        session,
        source_id=source.id,
        items=[
            NormalizedItem(
                external_id="priv",
                url="https://pg/priv",
                title="bob private pagination item",
                content_text="body",
                published_at=NOW - timedelta(hours=2, minutes=30),
            )
        ],
        owner_user_id=bob.id,
        raw_dir=raw_dir,
        now=NOW,
    )
    add_shared("p4", "page item 4", NOW - timedelta(hours=3))
    add_shared("p5", "page item 5", NOW - timedelta(hours=4))
    return alice, bob


def test_feed_before_id_paginates_and_respects_isolation(session, raw_dir):
    alice, bob = setup_items_for_pagination(session, raw_dir)

    full = feed(session, user_id=alice.id)
    full_titles = [item.title for item in full]
    assert full_titles == ["page item 1", "page item 2", "page item 3", "page item 4", "page item 5"]
    assert "bob private pagination item" not in full_titles

    cursor = next(item for item in full if item.title == "page item 3")
    page = feed(
        session,
        user_id=alice.id,
        before_id=cursor.id,
        before_published_at=cursor.published_at,
    )
    page_titles = [item.title for item in page]
    assert page_titles == ["page item 4", "page item 5"]
    assert "bob private pagination item" not in page_titles


def test_feed_pagination_returns_every_item_exactly_once_in_order(session, raw_dir):
    """F2: keyset pagination must use a cursor that matches the sort key
    (published_at DESC NULLS LAST, id DESC). A cursor on `id` alone duplicates
    and drops rows whenever id does not move in lockstep with published_at --
    exactly the layout `setup_items_for_pagination` now creates."""
    alice, bob = setup_items_for_pagination(session, raw_dir)

    collected = []
    before_id = None
    before_published_at = None
    for _ in range(10):  # safety bound; 5 items at limit=2 needs 3 pages
        page = feed(
            session,
            user_id=alice.id,
            limit=2,
            before_id=before_id,
            before_published_at=before_published_at,
        )
        if not page:
            break
        collected.extend(page)
        before_id = page[-1].id
        before_published_at = page[-1].published_at

    titles = [item.title for item in collected]
    assert titles == [
        "page item 1",
        "page item 2",
        "page item 3",
        "page item 4",
        "page item 5",
    ]
    assert len(collected) == len({item.id for item in collected}), "duplicate row across pages"
    assert "bob private pagination item" not in titles


def test_feed_pagination_through_null_published_at_tail(session, raw_dir):
    """F2: items with published_at IS NULL sort last (NULLS LAST) and, among
    themselves, break ties on id DESC. The cursor must fall through to an
    id-only comparison once the cursor row itself is in that NULL tail -- a
    plain row-value comparison of (published_at, id) against the cursor would
    not do this, since SQL row comparison treats a NULL component as unknown
    rather than "sorts last"."""
    alice = User(email="alice-null@example.com", display_name="alice-null", created_at=NOW)
    session.add(alice)
    session.flush()
    source = Source(kind="rss", identifier="https://null.example.com/feed", tier=1, config_json={}, created_at=NOW)
    session.add(source)
    session.flush()

    def add(external_id, title, published_at):
        upsert_items(
            session,
            source_id=source.id,
            items=[
                NormalizedItem(
                    external_id=external_id,
                    url=f"https://null/{external_id}",
                    title=title,
                    content_text="body",
                    published_at=published_at,
                )
            ],
            owner_user_id=None,
            raw_dir=raw_dir,
            now=NOW,
        )

    # "dated item" sorts first (has a published_at). n1..n3 are all NULL and
    # sort last, ordered purely by id DESC among themselves.
    add("dated", "dated item", NOW)
    add("n1", "undated 1", None)
    add("n2", "undated 2", None)
    add("n3", "undated 3", None)

    full = feed(session, user_id=alice.id)
    assert [i.title for i in full] == ["dated item", "undated 3", "undated 2", "undated 1"]

    collected = []
    before_id = None
    before_published_at = None
    for _ in range(10):  # safety bound
        page = feed(
            session,
            user_id=alice.id,
            limit=2,
            before_id=before_id,
            before_published_at=before_published_at,
        )
        if not page:
            break
        collected.extend(page)
        before_id = page[-1].id
        before_published_at = page[-1].published_at

    assert [i.title for i in collected] == ["dated item", "undated 3", "undated 2", "undated 1"]
    assert len(collected) == len({i.id for i in collected})
