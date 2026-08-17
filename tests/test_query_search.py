from datetime import UTC, datetime, timedelta

from reachstore.adapters.base import NormalizedItem
from reachstore.models import Source, User
from reachstore.query import search
from reachstore.store import upsert_items

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def seed(session, raw_dir):
    user = User(email="u@example.com", display_name="u", created_at=NOW)
    session.add(user)
    session.flush()
    rss = Source(kind="rss", identifier="https://a/feed", tier=1, config_json={}, created_at=NOW)
    gh = Source(kind="github_repo", identifier="octo/repo", tier=1, config_json={}, created_at=NOW)
    session.add_all([rss, gh])
    session.flush()
    upsert_items(
        session,
        source_id=rss.id,
        items=[
            NormalizedItem(
                external_id="1",
                url="https://a/1",
                title="Postgres full text search",
                content_text="indexing documents with tsvector",
                published_at=NOW,
            ),
            NormalizedItem(
                external_id="2",
                url="https://a/2",
                title="Unrelated cooking post",
                content_text="how to roast garlic",
                published_at=NOW - timedelta(days=30),
            ),
        ],
        owner_user_id=None,
        raw_dir=raw_dir,
        now=NOW,
    )
    upsert_items(
        session,
        source_id=gh.id,
        items=[
            NormalizedItem(
                external_id="3",
                url="https://gh/3",
                title="Release v2 indexing",
                content_text="faster tsvector indexing",
                published_at=NOW,
            )
        ],
        owner_user_id=None,
        raw_dir=raw_dir,
        now=NOW,
    )
    return user


def test_search_matches_content_and_title(session, raw_dir):
    user = seed(session, raw_dir)
    titles = {i.title for i in search(session, user_id=user.id, q="tsvector")}
    assert titles == {"Postgres full text search", "Release v2 indexing"}


def test_search_ignores_non_matching_documents(session, raw_dir):
    user = seed(session, raw_dir)
    titles = {i.title for i in search(session, user_id=user.id, q="garlic")}
    assert titles == {"Unrelated cooking post"}


def test_search_filters_by_kind(session, raw_dir):
    user = seed(session, raw_dir)
    titles = {i.title for i in search(session, user_id=user.id, q="indexing", kinds=["github_repo"])}
    assert titles == {"Release v2 indexing"}


def test_search_filters_by_since(session, raw_dir):
    user = seed(session, raw_dir)
    results = search(session, user_id=user.id, q="roast", since=NOW - timedelta(days=1))
    assert results == []


def test_search_ranks_title_matches_above_body_matches(session, raw_dir):
    user = seed(session, raw_dir)
    results = search(session, user_id=user.id, q="indexing")
    assert results[0].title == "Release v2 indexing"
