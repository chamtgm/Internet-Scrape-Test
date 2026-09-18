from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, and_, desc, func, or_, select
from sqlalchemy.orm import Session, selectinload

from reachstore.models import FetchRun, Item, Source, Subscription

MAX_LIMIT = 200


def _clamp_limit(limit: int) -> int:
    """Clamp a caller-supplied limit into [1, MAX_LIMIT].

    `LIMIT -1` raises a Postgres error and there is no upper bound otherwise.
    Clamped here, in the query layer -- the single documented point of truth
    for reads -- rather than at each call site, so it protects every caller
    including ones that don't exist yet (e.g. a future HTTP query parameter).
    """
    return max(1, min(limit, MAX_LIMIT))


def visible_to(user_id: int) -> ColumnElement[bool]:
    """The one and only tenant-isolation predicate.

    An item is visible when it is shared (owner_user_id IS NULL) or owned by this user.
    Every read path must apply this.
    """
    return or_(Item.owner_user_id.is_(None), Item.owner_user_id == user_id)


def get_item(session: Session, *, user_id: int, item_id: int) -> Item | None:
    stmt = (
        select(Item)
        .options(selectinload(Item.source))
        .where(Item.id == item_id, visible_to(user_id))
    )
    return session.execute(stmt).scalars().one_or_none()


def feed(
    session: Session,
    *,
    user_id: int,
    limit: int = 50,
    before_id: int | None = None,
    before_published_at: datetime | None = None,
) -> list[Item]:
    """The user's feed, ordered newest first: published_at DESC NULLS LAST, id DESC.

    Paginate with a compound keyset cursor: pass `before_id` and
    `before_published_at` taken from the last item of the previous page.
    `before_published_at` may itself be None -- that is a legitimate cursor
    value (the previous page's last item had no published_at, i.e. it was in
    the NULLS LAST tail), not "no cursor". `before_id=None` means "first
    page".

    A cursor on `before_id` alone (the old behavior) is not supported: it
    only ever matches this sort key by accident (e.g. every row sharing the
    same published_at). In general it both duplicates and drops rows,
    because id does not move in lockstep with published_at -- adapters
    typically emit newest-first, so the newest item (highest published_at)
    is inserted first and gets the *lowest* id.
    """
    stmt = select(Item).options(selectinload(Item.source)).where(visible_to(user_id))
    if before_id is not None:
        if before_published_at is not None:
            stmt = stmt.where(
                or_(
                    Item.published_at.is_(None),
                    Item.published_at < before_published_at,
                    and_(Item.published_at == before_published_at, Item.id < before_id),
                )
            )
        else:
            # The cursor row itself had a NULL published_at, i.e. it was
            # already in the NULLS LAST tail. Only other NULL rows with a
            # smaller id come after it.
            stmt = stmt.where(Item.published_at.is_(None), Item.id < before_id)
    stmt = (
        stmt.order_by(Item.published_at.desc().nulls_last(), desc(Item.id))
        .limit(_clamp_limit(limit))
    )
    return list(session.execute(stmt).scalars().all())


def search(
    session: Session,
    *,
    user_id: int,
    q: str,
    kinds: Sequence[str] | None = None,
    since: datetime | None = None,
    subscribed_only: bool = False,
    limit: int = 50,
) -> list[Item]:
    tsquery = func.websearch_to_tsquery("english", q)
    rank = func.ts_rank(Item.content_tsv, tsquery)

    conditions = [visible_to(user_id), Item.content_tsv.bool_op("@@")(tsquery)]
    if since is not None:
        conditions.append(Item.published_at >= since)

    stmt = select(Item).options(selectinload(Item.source))
    if kinds or subscribed_only:
        stmt = stmt.join(Source, Source.id == Item.source_id)
    if kinds:
        conditions.append(Source.kind.in_(list(kinds)))
    if subscribed_only:
        stmt = stmt.join(
            Subscription,
            and_(
                Subscription.source_id == Item.source_id,
                Subscription.user_id == user_id,
                Subscription.active.is_(True),
            ),
        )

    stmt = stmt.where(*conditions).order_by(desc(rank), desc(Item.id)).limit(_clamp_limit(limit))
    return list(session.execute(stmt).scalars().all())


def recent_fetch_statuses(session: Session, source_id: int, limit: int) -> list[str]:
    """Statuses of a source's most recent fetch_runs, newest first.

    Used by collect.py to derive the consecutive-failure streak without collect.py
    touching SQL directly.
    """
    stmt = (
        select(FetchRun.status)
        .where(FetchRun.source_id == source_id)
        .order_by(desc(FetchRun.started_at), desc(FetchRun.id))
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())


def last_run_started_at(session: Session, source_id: int, status: str) -> datetime | None:
    """started_at of the most recent fetch_run for a source with the given status."""
    stmt = (
        select(FetchRun.started_at)
        .where(FetchRun.source_id == source_id, FetchRun.status == status)
        .order_by(desc(FetchRun.started_at), desc(FetchRun.id))
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def sources_by_tier(session: Session, tier: int) -> list[Source]:
    """Sources belonging to a tier, in stable id order."""
    stmt = select(Source).where(Source.tier == tier).order_by(Source.id)
    return list(session.execute(stmt).scalars().all())


def get_source(session: Session, *, kind: str, identifier: str) -> Source | None:
    """Look up a source by its natural key (kind, identifier).

    Lets the CLI's `add-source` be idempotent (checking before inserting
    rather than catching IntegrityError) without cli.py building a query
    directly -- all SQL lives in store.py and query.py.
    """
    stmt = select(Source).where(Source.kind == kind, Source.identifier == identifier)
    return session.execute(stmt).scalars().one_or_none()


@dataclass(frozen=True)
class CatalogEntry:
    """A source as a non-admin sees it: enough to decide whether to subscribe,
    and nothing about its health. Diagnostics stay in SourceStatus, which only
    /api/sources returns."""

    source_id: int
    kind: str
    identifier: str
    tier: int
    subscribed: bool


def catalog(session: Session, *, user_id: int) -> list[CatalogEntry]:
    """Every source, flagged with whether this user subscribes to it.

    A LEFT JOIN rather than two queries and a set intersection: one round trip,
    and the flag cannot drift from the row it describes.
    """
    rows = session.execute(
        select(
            Source.id,
            Source.kind,
            Source.identifier,
            Source.tier,
            Subscription.id.isnot(None),
        )
        .select_from(Source)
        .outerjoin(
            Subscription,
            (Subscription.source_id == Source.id)
            & (Subscription.user_id == user_id)
            & (Subscription.active.is_(True)),
        )
        .order_by(Source.tier, Source.identifier)
    ).all()
    return [
        CatalogEntry(
            source_id=r[0], kind=r[1], identifier=r[2], tier=r[3], subscribed=bool(r[4])
        )
        for r in rows
    ]


@dataclass(frozen=True)
class SourceStatus:
    source_id: int
    kind: str
    identifier: str
    last_status: str | None
    last_run_at: datetime | None
    consecutive_failures: int
    needs_attention: bool
    error_text: str | None
    item_count: int


def source_health(session: Session) -> list[SourceStatus]:
    """Global operator view of every source's collection health.

    Deliberately not scoped to a user. Sources have no owner -- content is
    shared and interest is per-user via `subscriptions` -- so returning every
    source is a defensible operator view. It is deliberately NOT filtered by
    `subscriptions` either: this is the operator's view of every source's
    health, not a per-user one, so narrowing it to what one admin happens to
    subscribe to would hide sources nobody is watching yet. Per-user
    narrowing belongs to `/api/catalog`, the non-admin surface.

    This function used to take (and ignore) a `user_id` parameter, which
    looked like tenant isolation but was not: source identifiers are not
    innocuous (a private RSS feed URL can carry a token; a `github_repo`
    identifier can name a private repo), which is why per-user scoping now
    lives in `/api/catalog` rather than here.

    Derives everything from fetch_runs; nothing here is stored state.
    """
    # Local import: a module-level import here would create a cycle, because
    # `collect` imports `query` (for recent_fetch_statuses, last_run_started_at,
    # and sources_by_tier).
    from reachstore.collect import FAILURE_LIMIT, consecutive_failures

    sources = session.execute(select(Source).order_by(Source.id)).scalars().all()
    counts = dict(
        session.execute(
            select(Item.source_id, func.count(Item.id)).group_by(Item.source_id)
        ).all()
    )

    statuses: list[SourceStatus] = []
    for source in sources:
        last = session.execute(
            select(FetchRun)
            .where(FetchRun.source_id == source.id)
            .order_by(desc(FetchRun.started_at))
            .limit(1)
        ).scalars().one_or_none()
        failures = consecutive_failures(session, source.id)
        statuses.append(
            SourceStatus(
                source_id=source.id,
                kind=source.kind,
                identifier=source.identifier,
                last_status=last.status if last else None,
                last_run_at=last.started_at if last else None,
                consecutive_failures=failures,
                needs_attention=failures >= FAILURE_LIMIT,
                error_text=last.error_text if last else None,
                # Global, unfiltered count -- consistent with this whole
                # function being an operator view, not a per-user one. Under
                # real users (Plan 2) this would report items other users
                # hold under a shared source, not just this user's own.
                item_count=counts.get(source.id, 0),
            )
        )
    return statuses
