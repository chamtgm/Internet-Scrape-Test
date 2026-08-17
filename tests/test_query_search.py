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


def seed_field_weight_case(session, raw_dir):
    """Two items with equal term frequency (one occurrence of "kestrel" each),
    differing only in which field carries the term. "kestrel" appears nowhere
    else in this file's fixtures, so no other seeded row can interfere.
    """
    user = User(email="w@example.com", display_name="w", created_at=NOW)
    session.add(user)
    session.flush()
    source = Source(kind="rss", identifier="https://weight/feed", tier=1, config_json={}, created_at=NOW)
    session.add(source)
    session.flush()

    # Insert the title item FIRST and the body item SECOND. `search` orders by
    # desc(rank), desc(Item.id), so the later-inserted row has the higher id and
    # wins any rank tie. If field weighting is broken and the ranks tie, the body
    # item (higher id) sorts first and this test FAILS. Inserting in the other
    # order would let the test pass on a tie, which would defeat its purpose -
    # do not reorder these two calls.
    upsert_items(
        session,
        source_id=source.id,
        items=[
            NormalizedItem(
                external_id="w1",
                url="https://w/1",
                title="Kestrel release notes",
                content_text="nothing relevant here",
                published_at=NOW,
            )
        ],
        owner_user_id=None,
        raw_dir=raw_dir,
        now=NOW,
    )
    upsert_items(
        session,
        source_id=source.id,
        items=[
            NormalizedItem(
                external_id="w2",
                url="https://w/2",
                title="Nothing relevant",
                content_text="kestrel appears once here",
                published_at=NOW,
            )
        ],
        owner_user_id=None,
        raw_dir=raw_dir,
        now=NOW,
    )
    return user


def test_title_match_outranks_body_match(session, raw_dir):
    user = seed_field_weight_case(session, raw_dir)
    results = search(session, user_id=user.id, q="kestrel")
    assert len(results) == 2
    assert results[0].title == "Kestrel release notes"
