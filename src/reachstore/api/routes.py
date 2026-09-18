from __future__ import annotations

from datetime import UTC, datetime

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Depends,
    HTTPException,
    Query,
    Response,
)
from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from reachstore import query
from reachstore.api import collect_runner
from reachstore.api.auth import (
    COOKIE_NAME,
    SESSION_LIFETIME,
    create_session,
    delete_session,
    find_user_by_email,
    get_current_user,
    spend_dummy_verify,
    verify_password,
)
from reachstore.api.deps import DEFAULT_USER_ID, get_session
from reachstore.api.schemas import (
    CollectRequest,
    CollectResponse,
    Cursor,
    FeedResponse,
    ItemDetail,
    ItemSummary,
    LoginRequest,
    SearchResponse,
    SourcesResponse,
    SourceStatusOut,
    UserOut,
)
from reachstore.models import Item, User

router = APIRouter(prefix="/api")

EXCERPT_CHARS = 240


@router.get("/sources", response_model=SourcesResponse)
def list_sources(session: Session = Depends(get_session)) -> SourcesResponse:
    statuses = query.source_health(session)
    return SourcesResponse(
        sources=[SourceStatusOut(**vars(s)) for s in statuses],
        collecting=collect_runner.is_running(),
    )


@router.post(
    "/collect",
    response_model=CollectResponse,
    status_code=202,
    responses={409: {"model": CollectResponse}},
)
def post_collect(
    body: CollectRequest, background: BackgroundTasks, response: Response
) -> CollectResponse:
    # try_start() claims the slot synchronously, here in the handler -- not
    # inside the background task. A background task runs after the response
    # has already been sent, so checking there leaves a window where a second
    # request would also see no run in flight and also report started=True.
    if not collect_runner.try_start():
        response.status_code = 409
        return CollectResponse(
            started=False, reason="a collection run is already in progress"
        )
    background.add_task(collect_runner.run_collection, body.tier, body.force)
    return CollectResponse(started=True, tier=body.tier)


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
    limit: int = Query(50, ge=1, le=query.MAX_LIMIT),
    before_published_at: AwareDatetime | None = None,
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
    limit: int = Query(50, ge=1, le=query.MAX_LIMIT),
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


def _set_session_cookie(response: Response, token: str) -> None:
    """One place that writes the cookie, so login and setup cannot drift.

    `secure` is deliberately absent: there is no HTTPS on localhost and
    setting it would stop the cookie being sent at all. This is a decision,
    not an oversight.
    """
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,
        samesite="lax",
        path="/",
    )


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
    )


@router.post("/auth/login", response_model=UserOut)
def post_login(
    body: LoginRequest, response: Response, session: Session = Depends(get_session)
) -> UserOut:
    """401 with one identical body for a wrong password and an unknown email.

    The unknown-email branch still spends a full password verification, so the
    two cases take comparable time. Without that, latency alone reveals which
    addresses have accounts.
    """
    user = find_user_by_email(session, body.email)
    if user is None:
        spend_dummy_verify()
        raise HTTPException(status_code=401, detail="invalid email or password")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid email or password")

    token = create_session(session, user_id=user.id, now=datetime.now(UTC))
    session.commit()
    _set_session_cookie(response, token)
    return _user_out(user)


@router.post("/auth/logout")
def post_logout(
    response: Response,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    token: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> dict[str, bool]:
    if token is not None:
        delete_session(session, token=token)
        session.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/auth/me", response_model=UserOut)
def get_me(user: User = Depends(get_current_user)) -> UserOut:
    return _user_out(user)
