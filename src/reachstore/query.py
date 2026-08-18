from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, and_, desc, func, or_, select
from sqlalchemy.orm import Session

from reachstore.models import FetchRun, Item, Source, Subscription


def visible_to(user_id: int) -> ColumnElement[bool]:
    """The one and only tenant-isolation predicate.

    An item is visible when it is shared (owner_user_id IS NULL) or owned by this user.
    Every read path must apply this.
    """
    return or_(Item.owner_user_id.is_(None), Item.owner_user_id == user_id)


def get_item(session: Session, *, user_id: int, item_id: int) -> Item | None:
    stmt = select(Item).where(Item.id == item_id, visible_to(user_id))
    return session.execute(stmt).scalars().one_or_none()


def feed(
    session: Session, *, user_id: int, limit: int = 50, before_id: int | None = None
) -> list[Item]:
    stmt = select(Item).where(visible_to(user_id))
    if before_id is not None:
        stmt = stmt.where(Item.id < before_id)
    stmt = stmt.order_by(Item.published_at.desc().nulls_last(), desc(Item.id)).limit(limit)
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

    stmt = select(Item)
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

    stmt = stmt.where(*conditions).order_by(desc(rank), desc(Item.id)).limit(limit)
    return list(session.execute(stmt).scalars().all())


def recent_fetch_statuses(session: Session, source_id: int, limit: int) -> list[str]:
    """Statuses of a source's most recent fetch_runs, newest first.

    Used by collect.py to derive the consecutive-failure streak without collect.py
    touching SQL directly.
    """
    stmt = (
        select(FetchRun.status)
        .where(FetchRun.source_id == source_id)
        .order_by(desc(FetchRun.started_at))
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())


def last_run_started_at(session: Session, source_id: int, status: str) -> datetime | None:
    """started_at of the most recent fetch_run for a source with the given status."""
    stmt = (
        select(FetchRun.started_at)
        .where(FetchRun.source_id == source_id, FetchRun.status == status)
        .order_by(desc(FetchRun.started_at))
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def sources_by_tier(session: Session, tier: int) -> list[Source]:
    """Sources belonging to a tier, in stable id order."""
    stmt = select(Source).where(Source.tier == tier).order_by(Source.id)
    return list(session.execute(stmt).scalars().all())


@dataclass(frozen=True)
class SourceStatus:
    source_id: int
    kind: str
    identifier: str
    last_status: str | None
    last_run_at: datetime | None
    consecutive_failures: int
    needs_attention: bool


def source_health(session: Session, *, user_id: int) -> list[SourceStatus]:
    """Derive per-source health from fetch_runs. Nothing here is stored state."""
    from reachstore.collect import FAILURE_LIMIT, consecutive_failures

    sources = session.execute(select(Source).order_by(Source.id)).scalars().all()

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
            )
        )
    return statuses
