from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from reachstore import query
from reachstore.adapters.base import Adapter
from reachstore.models import FetchRun, Source
from reachstore.store import upsert_items

FAILURE_LIMIT = 5
BASE_BACKOFF = timedelta(minutes=15)
MAX_BACKOFF = timedelta(hours=24)


@dataclass(frozen=True)
class CollectResult:
    source_id: int
    status: str
    items_found: int
    items_new: int
    error_text: str | None


def consecutive_failures(session: Session, source_id: int) -> int:
    """Length of the current unbroken failure streak, newest run first."""
    statuses = query.recent_fetch_statuses(session, source_id, FAILURE_LIMIT)
    streak = 0
    for status in statuses:
        if status != "failed":
            break
        streak += 1
    return streak


def should_attempt(session: Session, source_id: int, now: datetime) -> bool:
    """False while backing off, and permanently once the circuit breaker opens."""
    failures = consecutive_failures(session, source_id)
    if failures == 0:
        return True
    if failures >= FAILURE_LIMIT:
        return False

    last_failure_at = query.last_run_started_at(session, source_id, "failed")
    if last_failure_at is None:
        # Unreachable in practice: failures > 0 means the most recent run was a
        # failure, so a failed run necessarily exists. Fail safe rather than crash.
        return True
    delay = min(BASE_BACKOFF * (2 ** (failures - 1)), MAX_BACKOFF)
    return now >= last_failure_at + delay


def collect_source(
    session: Session,
    *,
    source: Source,
    adapter: Adapter,
    raw_dir: Path,
    now: datetime,
    owner_user_id: int | None = None,
) -> CollectResult:
    """Fetch one source. Never raises: failures are recorded and returned.

    Catches broad Exception (not only AdapterError) because adapters can leak
    exceptions other than AdapterError on malformed upstream data (a KeyError on a
    missing field, an AttributeError on an unexpected JSON shape). This function is
    the bulkhead and must not depend on every adapter being perfectly well-behaved.
    KeyboardInterrupt and SystemExit are BaseException subclasses, not Exception, so
    they still propagate.
    """
    run = FetchRun(
        source_id=source.id, started_at=now, status="running", items_found=0, items_new=0
    )
    session.add(run)
    session.flush()

    try:
        since = query.last_run_started_at(session, source.id, "success")
        items = adapter.fetch(source.identifier, since)
        new_count = upsert_items(
            session,
            source_id=source.id,
            items=items,
            owner_user_id=owner_user_id,
            raw_dir=raw_dir,
            now=now,
        )
    except Exception as exc:  # bulkhead: one source must never abort the run
        error_text = f"{type(exc).__name__}: {exc}"
        run.status = "failed"
        run.finished_at = now
        run.error_text = error_text
        session.flush()
        return CollectResult(source.id, "failed", 0, 0, error_text)

    run.status = "success"
    run.finished_at = now
    run.items_found = len(items)
    run.items_new = new_count
    session.flush()
    return CollectResult(source.id, "success", len(items), new_count, None)


def collect_tier(
    session: Session,
    *,
    tier: int,
    registry: dict[str, Adapter],
    raw_dir: Path,
    now: datetime,
    force: bool = False,
) -> list[CollectResult]:
    """Collect every source in a tier, isolating failures per source."""
    sources = query.sources_by_tier(session, tier)

    results: list[CollectResult] = []
    for source in sources:
        adapter = registry.get(source.kind)
        if adapter is None:
            continue
        if not force and not should_attempt(session, source.id, now):
            continue
        results.append(
            collect_source(session, source=source, adapter=adapter, raw_dir=raw_dir, now=now)
        )
    return results
