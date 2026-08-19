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
    """Fetch one source. Never raises for failures encountered while doing this
    source's work: whether the adapter blows up, or upsert_items hits a database
    error while writing malformed data (e.g. a NOT NULL violation from an item with
    a missing required field), the failure is recorded as a failed fetch_run and
    returned as a failed CollectResult instead of propagating.

    Catches broad Exception (not only AdapterError) because adapters can leak
    exceptions other than AdapterError on malformed upstream data (a KeyError on a
    missing field, an AttributeError on an unexpected JSON shape). This function is
    the bulkhead and must not depend on every adapter being perfectly well-behaved.
    KeyboardInterrupt and SystemExit are BaseException subclasses, not Exception, so
    they still propagate.

    The fetch-and-store work runs inside a SAVEPOINT (session.begin_nested()):
    a database-level error aborts the enclosing Postgres transaction, so without
    the savepoint the flush that records the failure below would itself raise
    against that aborted transaction, escaping this function. Recording the
    failure is itself wrapped so that even if persisting the failed run fails,
    this function still returns a failed CollectResult rather than raising.

    Not guarded: creating the initial "running" fetch_run row below, before any
    adapter or store code runs. A failure there means the database itself is
    unreachable -- an infrastructure precondition, not a per-source data problem --
    and is out of scope for this function's isolation.
    """
    run = FetchRun(
        source_id=source.id, started_at=now, status="running", items_found=0, items_new=0
    )
    session.add(run)
    session.flush()

    try:
        # SAVEPOINT: a DB error inside this block must not poison the outer
        # transaction, which is still needed below to record the failure.
        with session.begin_nested():
            # F1: always pass None as `since`. The watermark used to be the
            # last successful run's start time, but feed lag means an item
            # published before that run can still be missing from the
            # upstream feed at the moment the run executes, and only appear
            # afterward -- under the old logic such an item was skipped on
            # that run and every run after it, permanently and silently.
            # Re-seeing old items is idempotent (ON CONFLICT DO NOTHING) and
            # costs only a few skipped round-trips, a trade worth making
            # against permanent silent data loss. `since` stays a parameter
            # on Adapter.fetch and every adapter for Plan 3's paginated
            # Tier-2/3 adapters, whose callers will derive it from actually
            # stored data rather than a run timestamp.
            items = adapter.fetch(source.identifier, None)
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
        try:
            run.status = "failed"
            run.finished_at = now
            run.error_text = error_text
            session.flush()
        except Exception:
            # Recording the failure itself failed. The bulkhead must still not
            # raise -- report the original failure via the returned CollectResult
            # even though it could not be persisted to fetch_runs.
            pass
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
