"""Tenant isolation asserted through HTTP, not just through query.visible_to.

Before this task the API had one hard-coded user, so `owner_user_id` could
only ever be tested at the query layer. Now that a request carries a real
identity, the isolation is provable end to end.
"""

from datetime import UTC, datetime

from reachstore.adapters.base import NormalizedItem
from reachstore.models import Source
from reachstore.store import upsert_items

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


def _source(session):
    source = Source(
        kind="rss", identifier="https://t/feed", tier=1, config_json={}, created_at=NOW
    )
    session.add(source)
    session.flush()
    return source


def _item(session, source, *, external_id, owner_user_id, raw_dir):
    upsert_items(
        session,
        source_id=source.id,
        items=[
            NormalizedItem(
                external_id=external_id,
                url=f"https://t/{external_id}",
                title=external_id,
                content_text="shared vocabulary term",
                published_at=NOW,
            )
        ],
        owner_user_id=owner_user_id,
        raw_dir=raw_dir,
        now=NOW,
    )


def test_private_items_are_invisible_to_other_users(session, client_for, raw_dir):
    alice_client, alice, _ = client_for()
    bob_client, bob, _ = client_for()
    source = _source(session)

    _item(session, source, external_id="public", owner_user_id=None, raw_dir=raw_dir)
    _item(session, source, external_id="alices", owner_user_id=alice.id, raw_dir=raw_dir)
    _item(session, source, external_id="bobs", owner_user_id=bob.id, raw_dir=raw_dir)
    session.flush()

    alice_titles = {i["title"] for i in alice_client.get("/api/feed").json()["items"]}
    bob_titles = {i["title"] for i in bob_client.get("/api/feed").json()["items"]}

    assert alice_titles == {"public", "alices"}
    assert bob_titles == {"public", "bobs"}


def test_another_users_item_is_404_not_403(session, client_for, raw_dir):
    """Indistinguishable from a nonexistent id, so the endpoint cannot be used
    to probe for the existence of someone else's private items."""
    alice_client, alice, _ = client_for()
    bob_client, _bob, _ = client_for()
    source = _source(session)

    _item(session, source, external_id="alices", owner_user_id=alice.id, raw_dir=raw_dir)
    session.flush()

    item_id = alice_client.get("/api/feed").json()["items"][0]["id"]
    assert alice_client.get(f"/api/items/{item_id}").status_code == 200
    assert bob_client.get(f"/api/items/{item_id}").status_code == 404
    assert bob_client.get("/api/items/999999").status_code == 404


def test_search_is_also_isolated(session, client_for, raw_dir):
    alice_client, alice, _ = client_for()
    bob_client, _bob, _ = client_for()
    source = _source(session)

    _item(session, source, external_id="alices", owner_user_id=alice.id, raw_dir=raw_dir)
    session.flush()

    assert len(alice_client.get("/api/search?q=vocabulary").json()["items"]) == 1
    assert bob_client.get("/api/search?q=vocabulary").json()["items"] == []
