from datetime import UTC, datetime

from reachstore.adapters.base import NormalizedItem
from reachstore.models import Source
from reachstore.store import upsert_items

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


def make_source(session, identifier, *, tier=1, kind="rss"):
    source = Source(
        kind=kind, identifier=identifier, tier=tier, config_json={}, created_at=NOW
    )
    session.add(source)
    session.flush()
    return source


def add_item(session, source, *, external_id, text, raw_dir):
    upsert_items(
        session,
        source_id=source.id,
        items=[
            NormalizedItem(
                external_id=external_id,
                url=f"https://x/{external_id}",
                title=external_id,
                content_text=text,
                published_at=NOW,
            )
        ],
        owner_user_id=None,
        raw_dir=raw_dir,
        now=NOW,
    )
    session.flush()


# --- catalog -----------------------------------------------------------------

def test_catalog_lists_every_source_with_a_subscribed_flag(session, user_client):
    make_source(session, "https://a/feed")
    make_source(session, "https://b/feed", tier=2)

    body = user_client.get("/api/catalog").json()
    rows = {r["identifier"]: r for r in body["sources"]}
    assert set(rows) == {"https://a/feed", "https://b/feed"}
    assert rows["https://a/feed"]["subscribed"] is False
    assert rows["https://b/feed"]["tier"] == 2


def test_catalog_reflects_only_the_requesting_users_subscriptions(session, client_for):
    alice_client, _alice, _ = client_for()
    bob_client, _bob, _ = client_for()
    source = make_source(session, "https://shared/feed")

    assert alice_client.put(f"/api/subscriptions/{source.id}").status_code == 204

    def subscribed(client):
        return client.get("/api/catalog").json()["sources"][0]["subscribed"]

    assert subscribed(alice_client) is True
    assert subscribed(bob_client) is False


def test_catalog_omits_health_and_error_fields(session, user_client):
    """The catalog is the non-admin view. Diagnostics stay on /api/sources."""
    make_source(session, "https://a/feed")
    row = user_client.get("/api/catalog").json()["sources"][0]
    assert set(row) == {"source_id", "kind", "identifier", "tier", "subscribed"}


# --- subscribe / unsubscribe -------------------------------------------------

def test_subscribe_is_idempotent(session, user_client):
    source = make_source(session, "https://a/feed")
    for _ in range(3):
        assert user_client.put(f"/api/subscriptions/{source.id}").status_code == 204
    assert user_client.get("/api/catalog").json()["sources"][0]["subscribed"] is True


def test_unsubscribe_is_idempotent_and_works_when_never_subscribed(session, user_client):
    source = make_source(session, "https://a/feed")
    for _ in range(3):
        assert user_client.delete(f"/api/subscriptions/{source.id}").status_code == 204
    assert user_client.get("/api/catalog").json()["sources"][0]["subscribed"] is False


def test_resubscribing_after_unsubscribing_works(session, user_client):
    """Unsubscribe clears the `active` flag rather than deleting the row, so
    re-subscribing has to reactivate it -- a plain insert would conflict."""
    source = make_source(session, "https://a/feed")
    user_client.put(f"/api/subscriptions/{source.id}")
    user_client.delete(f"/api/subscriptions/{source.id}")
    assert user_client.put(f"/api/subscriptions/{source.id}").status_code == 204
    assert user_client.get("/api/catalog").json()["sources"][0]["subscribed"] is True


def test_subscribing_to_an_unknown_source_is_404(user_client):
    assert user_client.put("/api/subscriptions/999999").status_code == 404


# --- subscribed_only search --------------------------------------------------

def test_search_subscribed_only_filters_by_subscription(session, user_client, raw_dir):
    a = make_source(session, "https://a/feed")
    b = make_source(session, "https://b/feed")
    add_item(session, a, external_id="from-a", text="shared keyword", raw_dir=raw_dir)
    add_item(session, b, external_id="from-b", text="shared keyword", raw_dir=raw_dir)
    user_client.put(f"/api/subscriptions/{a.id}")

    everything = user_client.get("/api/search?q=keyword").json()["items"]
    assert len(everything) == 2

    filtered = user_client.get("/api/search?q=keyword&subscribed_only=true").json()["items"]
    assert [i["title"] for i in filtered] == ["from-a"]


def test_subscribed_only_defaults_to_false(session, user_client, raw_dir):
    """Reading is unfiltered unless asked. Subscriptions narrow the view; they
    do not gate access -- collection stays tier-driven."""
    a = make_source(session, "https://a/feed")
    add_item(session, a, external_id="from-a", text="shared keyword", raw_dir=raw_dir)

    assert len(user_client.get("/api/search?q=keyword").json()["items"]) == 1


def test_unsubscribing_removes_items_from_a_subscribed_only_search(session, user_client, raw_dir):
    a = make_source(session, "https://a/feed")
    add_item(session, a, external_id="from-a", text="shared keyword", raw_dir=raw_dir)
    user_client.put(f"/api/subscriptions/{a.id}")
    user_client.delete(f"/api/subscriptions/{a.id}")

    assert user_client.get("/api/search?q=keyword&subscribed_only=true").json()["items"] == []


def test_catalog_requires_a_session(anon_client):
    assert anon_client.get("/api/catalog").status_code == 401


def test_subscribing_requires_a_session(anon_client):
    assert anon_client.put("/api/subscriptions/1").status_code == 401
