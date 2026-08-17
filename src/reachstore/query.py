from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, and_, desc, func, or_, select
from sqlalchemy.orm import Session

from reachstore.models import Item, Source, Subscription


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
