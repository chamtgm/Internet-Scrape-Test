from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from reachstore import query
from reachstore.api.deps import DEFAULT_USER_ID, get_session
from reachstore.api.schemas import (
    Cursor,
    FeedResponse,
    ItemDetail,
    ItemSummary,
    SearchResponse,
    SourcesResponse,
    SourceStatusOut,
)
from reachstore.models import Item

router = APIRouter(prefix="/api")

EXCERPT_CHARS = 240


@router.get("/sources", response_model=SourcesResponse)
def list_sources(session: Session = Depends(get_session)) -> SourcesResponse:
    statuses = query.source_health(session)
    return SourcesResponse(sources=[SourceStatusOut(**vars(s)) for s in statuses])


def _summary(item: Item) -> ItemSummary:
    return ItemSummary(
        id=item.id,
        title=item.title,
        url=item.url,
        author_handle=item.author_handle,
        published_at=item.published_at,
        source_id=item.source_id,
        source_kind=item.source.kind,
        source_identifier=item.source.identifier,
        # Collapse whitespace before truncating: stored text carries the
        # upstream's newlines and indentation, which would otherwise eat most
        # of the excerpt budget.
        excerpt=" ".join(item.content_text.split())[:EXCERPT_CHARS],
    )


@router.get("/feed", response_model=FeedResponse)
def get_feed(
    session: Session = Depends(get_session),
    limit: int = Query(50, ge=1, le=200),
    before_published_at: datetime | None = None,
    before_id: int | None = None,
) -> FeedResponse:
    """One page of the feed, newest first.

    `before_published_at` is absent rather than null when the previous page's
    last item had no published_at. That is not a missing value: `query.feed`
    reads (before_id set, before_published_at None) as "continue through the
    NULLS LAST tail", which is exactly the right meaning.
    """
    items = query.feed(
        session,
        user_id=DEFAULT_USER_ID,
        limit=limit,
        before_id=before_id,
        before_published_at=before_published_at,
    )
    # A short page means the end. Only a full page can have more behind it.
    cursor = None
    if len(items) == limit:
        last = items[-1]
        cursor = Cursor(published_at=last.published_at, id=last.id)
    return FeedResponse(items=[_summary(i) for i in items], next_cursor=cursor)


@router.get("/search", response_model=SearchResponse)
def get_search(
    q: str = Query(..., min_length=1),
    kind: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> SearchResponse:
    items = query.search(
        session,
        user_id=DEFAULT_USER_ID,
        q=q,
        kinds=[kind] if kind else None,
        limit=limit,
    )
    return SearchResponse(items=[_summary(i) for i in items])


@router.get("/items/{item_id}", response_model=ItemDetail)
def get_one_item(item_id: int, session: Session = Depends(get_session)) -> ItemDetail:
    """404 both when the item does not exist and when it is not visible.

    The two are deliberately indistinguishable, so this endpoint cannot be
    used to probe for the existence of another user's private items once
    Plan 2 introduces real users.
    """
    item = query.get_item(session, user_id=DEFAULT_USER_ID, item_id=item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    return ItemDetail(
        **_summary(item).model_dump(),
        content_text=item.content_text,
        fetched_at=item.fetched_at,
    )
