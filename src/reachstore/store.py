from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from reachstore.adapters.base import NormalizedItem
from reachstore.models import Item


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_raw(raw_dir: Path, relative: Path, raw: dict[str, Any]) -> None:
    """Write the upstream payload to disk at raw_dir / relative."""
    target = raw_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(raw, ensure_ascii=False, default=str))


def upsert_items(
    session: Session,
    *,
    source_id: int,
    items: Sequence[NormalizedItem],
    owner_user_id: int | None,
    raw_dir: Path,
    now: datetime,
) -> int:
    """Insert items, skipping any that already exist. Returns the number inserted.

    Safe to call repeatedly with the same input: (source_id, external_id) is unique
    and conflicts are ignored.
    """
    inserted = 0
    for item in items:
        digest = content_hash(item.content_text)
        relative = Path(str(source_id)) / f"{content_hash(item.external_id)}.json"
        stmt = (
            insert(Item)
            .values(
                source_id=source_id,
                external_id=item.external_id,
                owner_user_id=owner_user_id,
                url=item.url,
                title=item.title,
                author_handle=item.author_handle,
                published_at=item.published_at,
                fetched_at=now,
                content_text=item.content_text,
                raw_path=str(relative) if item.raw else None,
                content_hash=digest,
            )
            .on_conflict_do_nothing(constraint="uq_items_source_external")
            .returning(Item.id)
        )
        if session.execute(stmt).scalar_one_or_none() is not None:
            if item.raw:
                _write_raw(raw_dir, relative, item.raw)
            inserted += 1
    session.flush()
    return inserted
