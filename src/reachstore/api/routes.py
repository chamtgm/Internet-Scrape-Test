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

from reachstore import query, store
from reachstore.api import collect_runner
from reachstore.api.auth import (
    COOKIE_NAME,
    MIN_PASSWORD_LENGTH,
    SESSION_LIFETIME,
    consume_invite,
    create_session,
    delete_session,
    find_user_by_email,
    get_current_user,
    hash_password,
    require_admin,
    spend_dummy_verify,
    verify_password,
)
from reachstore.api.deps import get_session
from reachstore.api.schemas import (
    CatalogEntryOut,
    CatalogResponse,
    CollectRequest,
    CollectResponse,
    Cursor,
    FeedResponse,
    ItemDetail,
    ItemSummary,
    LoginRequest,
    SearchResponse,
    SetupRequest,
    SourcesResponse,
    SourceStatusOut,
    UserOut,
)
from reachstore.models import Item, Source, User

router = APIRouter(prefix="/api")

EXCERPT_CHARS = 240


@router.get("/sources", response_model=SourcesResponse)
def list_sources(
    session: Session = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> SourcesResponse:
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
    body: CollectRequest,
    background: BackgroundTasks,
    response: Response,
    _admin: User = Depends(require_admin),
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
    user: User = Depends(get_current_user),
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
        user_id=user.id,
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
    subscribed_only: bool = False,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> SearchResponse:
    """`subscribed_only` narrows reading only.

    Collection stays tier-driven: unsubscribing hides a source from your view
    without stopping it being collected, and without affecting anyone else.
    Filtering at read time is reversible; filtering at ingest is not.
    """
    items = query.search(
        session,
        user_id=user.id,
        q=q,
        kinds=[kind] if kind else None,
        subscribed_only=subscribed_only,
        limit=limit,
    )
    return SearchResponse(items=[_summary(i) for i in items])


@router.get("/catalog", response_model=CatalogResponse)
def get_catalog(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> CatalogResponse:
    """Every source, with this user's subscription flag.

    Not admin-gated, because a non-admin has to see sources in order to
    subscribe to them -- and `source_identifier` already appears on every feed
    row, so identifiers were never operator-only. What is operator-only is the
    health and control surface on /api/sources.
    """
    entries = query.catalog(session, user_id=user.id)
    return CatalogResponse(sources=[CatalogEntryOut(**vars(e)) for e in entries])


@router.put("/subscriptions/{source_id}", status_code=204, response_class=Response)
def put_subscription(
    source_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    """PUT, not POST: the request means "make this subscription exist", which
    is idempotent by definition, so the verb is too.

    Returns an explicit empty Response rather than None. A 204 must carry no
    body, and letting FastAPI serialise a None return value through the
    default JSON response class is the kind of detail that differs between
    versions -- being explicit costs one line and cannot regress.
    """
    if session.get(Source, source_id) is None:
        raise HTTPException(status_code=404, detail="source not found")
    store.subscribe(session, user_id=user.id, source_id=source_id, now=datetime.now(UTC))
    session.commit()
    return Response(status_code=204)


@router.delete("/subscriptions/{source_id}", status_code=204, response_class=Response)
def delete_subscription(
    source_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    """204 even when no subscription existed -- the caller's desired state is
    reached either way, and a 404 here would leak nothing useful."""
    store.unsubscribe(session, user_id=user.id, source_id=source_id)
    session.commit()
    return Response(status_code=204)


@router.get("/items/{item_id}", response_model=ItemDetail)
def get_one_item(
    item_id: int,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ItemDetail:
    """404 both when the item does not exist and when it is not visible.

    The two are deliberately indistinguishable, so this endpoint cannot be
    used to probe for the existence of another user's private items.
    """
    item = query.get_item(session, user_id=user.id, item_id=item_id)
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


@router.post("/auth/setup", response_model=UserOut)
def post_setup(
    body: SetupRequest, response: Response, session: Session = Depends(get_session)
) -> UserOut:
    """Redeem an invite: create the account and log it straight in.

    Unauthenticated by design -- it is how someone with no account gets one.
    Its access control is possession of a token that exists in exactly one
    place, the URL the operator handed over.

    One 400 with one message for every token failure -- unknown, already
    consumed, expired, password too short -- because distinguishing them would
    let a stranger probe which invites exist.

    An email that already has an account is the exception, and returns 409:
    whoever holds the token already knows the email it names, so the
    distinction leaks nothing they did not supply, and it is the one failure a
    person can act on.
    """
    now = datetime.now(UTC)

    # Validate the password BEFORE consuming the invite. Consuming first would
    # mean a typo burns a single-use link and the person has to go back to the
    # operator for a new one.
    if len(body.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail="invalid or expired setup link")

    invite = consume_invite(session, token=body.token, now=now)
    if invite is None:
        raise HTTPException(status_code=400, detail="invalid or expired setup link")

    taken = find_user_by_email(session, invite.email)
    if taken is not None:
        # The invite predates an account that now exists. It is spent either
        # way -- rolling it back would leave a link that can be retried
        # forever against an existing account.
        session.commit()
        raise HTTPException(status_code=409, detail="that email already has an account")

    user = User(
        email=invite.email,
        display_name=invite.display_name,
        password_hash=hash_password(body.password),
        is_admin=invite.is_admin,
        created_at=now,
    )
    session.add(user)
    session.flush()

    token = create_session(session, user_id=user.id, now=now)
    session.commit()
    _set_session_cookie(response, token)
    return _user_out(user)
