from datetime import UTC, datetime, timedelta

from reachstore.adapters.base import NormalizedItem
from reachstore.models import Source, User
from reachstore.query import MAX_LIMIT, _clamp_limit, search
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


def test_clamp_limit_boundaries():
    """F7: `LIMIT -1` raises a Postgres error and there is no upper bound
    otherwise. Direct check of the clamp math at its three edges."""
    assert _clamp_limit(0) == 1
    assert _clamp_limit(-1) == 1
    assert _clamp_limit(-1000) == 1
    assert _clamp_limit(1) == 1
    assert _clamp_limit(MAX_LIMIT) == MAX_LIMIT
    assert _clamp_limit(MAX_LIMIT + 1) == MAX_LIMIT
    assert _clamp_limit(10_000_000) == MAX_LIMIT


def test_search_with_negative_limit_does_not_raise_and_still_returns_a_result(session, raw_dir):
    """F7 integration proof: `LIMIT -1` is a genuine Postgres error. Both
    "indexing" items in `seed` match this query, so an unclamped limit=-1
    would raise before this even had a chance to return a row count."""
    user = seed(session, raw_dir)
    results = search(session, user_id=user.id, q="indexing", limit=-1)
    assert len(results) == 1


def test_search_with_zero_limit_still_returns_a_result(session, raw_dir):
    """limit=0 is valid SQL (LIMIT 0 -> zero rows) so it does not raise even
    unclamped, but zero results for a query with real matches is a bug in
    its own right worth guarding against."""
    user = seed(session, raw_dir)
    results = search(session, user_id=user.id, q="indexing", limit=0)
    assert len(results) == 1


def test_search_with_huge_limit_is_capped(session, raw_dir):
    user = seed(session, raw_dir)
    results = search(session, user_id=user.id, q="indexing", limit=10_000_000)
    assert len(results) <= MAX_LIMIT


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
