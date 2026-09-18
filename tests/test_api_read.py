from datetime import UTC, datetime, timedelta

from reachstore.adapters.base import NormalizedItem
from reachstore.models import Source
from reachstore.store import upsert_items

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def seed(session, raw_dir, count=5):
    source = Source(
        kind="rss", identifier="https://a/feed", tier=1, config_json={}, created_at=NOW
    )
    session.add(source)
    session.flush()
    items = [
        NormalizedItem(
            external_id=f"e{i}",
            url=f"https://a/{i}",
            title=f"Item {i}",
            content_text=f"body number {i} " + "padding " * 60,
            published_at=NOW - timedelta(days=i),
        )
        for i in range(count)
    ]
    upsert_items(
        session,
        source_id=source.id,
        items=items,
        owner_user_id=None,
        raw_dir=raw_dir,
        now=NOW,
    )
    return source


def test_feed_returns_items_newest_first_with_source_labels(session, raw_dir, user_client):
    seed(session, raw_dir)
    body = user_client.get("/api/feed").json()
    assert [i["title"] for i in body["items"]] == [f"Item {i}" for i in range(5)]
    assert body["items"][0]["source_kind"] == "rss"
    assert body["items"][0]["source_identifier"] == "https://a/feed"


def test_feed_excerpt_is_truncated_and_detail_is_not(session, raw_dir, user_client):
    seed(session, raw_dir)
    client = user_client
    summary = client.get("/api/feed").json()["items"][0]
    assert len(summary["excerpt"]) <= 240
    detail = client.get(f"/api/items/{summary['id']}").json()
    assert len(detail["content_text"]) > 240
    assert detail["content_text"].startswith("body number 0")
    assert detail["fetched_at"]


def test_feed_paginates_without_gaps_or_duplicates(session, raw_dir, user_client):
    """Cursor walk built to force both hard cases in query.feed's sort key
    (published_at DESC NULLS LAST, id DESC): three items share one
    published_at, split across a page boundary so the id DESC tie-break arm
    (`published_at == before_published_at AND id < before_id`) has to fire
    to produce a result row rather than sit unused; two items have
    published_at=None, so a cursor genuinely carries a null through the
    before_published_at round trip -- the client's contract is to omit the
    query param entirely, not send literal null, and that omission has to
    survive being encoded, sent, and decoded again.
    """
    source = Source(
        kind="rss", identifier="https://a/feed", tier=1, config_json={}, created_at=NOW
    )
    session.add(source)
    session.flush()
    items = [
        NormalizedItem(
            external_id=f"e{i}",
            url=f"https://a/{i}",
            title=f"Item {i}",
            content_text=f"body number {i}",
            published_at=NOW if i < 3 else None,
        )
        for i in range(5)
    ]
    upsert_items(
        session,
        source_id=source.id,
        items=items,
        owner_user_id=None,
        raw_dir=raw_dir,
        now=NOW,
    )
    client = user_client
    seen, cursor, pages = [], None, 0
    saw_null_cursor = False
    while pages < 10:
        params = {"limit": 2}
        if cursor is not None:
            params["before_id"] = cursor["id"]
            # Omitted entirely when null -- that is the NULLS LAST tail cursor.
            if cursor["published_at"] is not None:
                params["before_published_at"] = cursor["published_at"]
            else:
                saw_null_cursor = True
        body = client.get("/api/feed", params=params).json()
        seen.extend(i["id"] for i in body["items"])
        cursor = body["next_cursor"]
        pages += 1
        if cursor is None:
            break
    assert len(seen) == 5
    assert len(set(seen)) == 5
    assert saw_null_cursor, "cursor never carried a null published_at through the round trip"


def test_search_returns_hits_and_filters_by_kind(session, raw_dir, user_client):
    seed(session, raw_dir)
    client = user_client
    assert client.get("/api/search", params={"q": "padding"}).json()["items"]
    narrowed = client.get("/api/search", params={"q": "padding", "kind": "github_repo"}).json()
    assert narrowed["items"] == []


def test_search_results_carry_source_labels(session, raw_dir, user_client):
    seed(session, raw_dir)
    hits = user_client.get("/api/search", params={"q": "padding"}).json()["items"]
    assert hits[0]["source_identifier"] == "https://a/feed"


def test_missing_item_is_404(session, raw_dir, user_client):
    seed(session, raw_dir)
    assert user_client.get("/api/items/999999").status_code == 404


def test_bad_limit_is_422(session, raw_dir, user_client):
    seed(session, raw_dir)
    client = user_client
    assert client.get("/api/feed", params={"limit": "banana"}).status_code == 422
    assert client.get("/api/feed", params={"limit": 0}).status_code == 422
    assert client.get("/api/search", params={"q": ""}).status_code == 422
