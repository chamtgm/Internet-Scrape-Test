from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from reachstore.adapters.base import AdapterError, NormalizedItem
from reachstore.collect import (
    BASE_BACKOFF,
    CollectResult,
    collect_source,
    collect_tier,
    consecutive_failures,
    should_attempt,
)
from reachstore.models import FetchRun, Item, Source
from reachstore.query import source_health

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


class StubAdapter:
    def __init__(self, kind: str, items=None, error: Exception | None = None):
        self.kind = kind
        self.tier = 1
        self._items = items or []
        self._error = error
        self.calls = 0
        self.received_since = "unset"

    def fetch(self, identifier: str, since):
        self.calls += 1
        self.received_since = since
        if self._error is not None:
            raise self._error
        return self._items


def add_source(session, kind="rss", identifier="https://a/feed", tier=1) -> Source:
    source = Source(kind=kind, identifier=identifier, tier=tier, config_json={}, created_at=NOW)
    session.add(source)
    session.flush()
    return source


def one_item() -> list[NormalizedItem]:
    return [NormalizedItem(external_id="1", url="https://a/1", title="t", content_text="body")]


def test_successful_collection_stores_items_and_records_run(session, raw_dir):
    source = add_source(session)
    result = collect_source(
        session, source=source, adapter=StubAdapter("rss", one_item()), raw_dir=raw_dir, now=NOW
    )
    assert result == CollectResult(source.id, "success", 1, 1, None)
    assert session.execute(select(Item)).scalars().all()
    run = session.execute(select(FetchRun)).scalars().one()
    assert run.status == "success"
    assert run.items_new == 1
    assert run.finished_at is not None


def test_collect_source_never_passes_a_since_watermark_to_the_adapter(session, raw_dir):
    """F1: passing the last successful run's start_at as `since` causes items
    that only appear in the upstream feed after that run (feed lag) to be
    skipped forever, silently. Seed a successful fetch_run first so this test
    would fail against the old code, which passed that run's started_at as
    `since` on every subsequent collection."""
    source = add_source(session)
    session.add(
        FetchRun(
            source_id=source.id,
            started_at=NOW - timedelta(hours=1),
            finished_at=NOW - timedelta(hours=1),
            status="success",
            items_found=1,
            items_new=1,
        )
    )
    session.flush()

    adapter = StubAdapter("rss", one_item())
    collect_source(session, source=source, adapter=adapter, raw_dir=raw_dir, now=NOW)

    assert adapter.received_since is None


def test_failing_adapter_records_failed_run_and_does_not_raise(session, raw_dir):
    source = add_source(session)
    result = collect_source(
        session,
        source=source,
        adapter=StubAdapter("rss", error=AdapterError("feed is gone")),
        raw_dir=raw_dir,
        now=NOW,
    )
    assert result.status == "failed"
    assert "feed is gone" in result.error_text
    run = session.execute(select(FetchRun)).scalars().one()
    assert run.status == "failed"


def test_one_failing_source_does_not_abort_the_run(session, raw_dir):
    good = add_source(session, identifier="https://good/feed")
    bad = add_source(session, identifier="https://bad/feed")
    registry = {"rss": StubAdapter("rss", one_item())}
    failing = {"rss": StubAdapter("rss", error=AdapterError("boom"))}

    results = []
    results.append(collect_source(session, source=bad, adapter=failing["rss"], raw_dir=raw_dir, now=NOW))
    results.append(collect_source(session, source=good, adapter=registry["rss"], raw_dir=raw_dir, now=NOW))
    assert [r.status for r in results] == ["failed", "success"]


def test_collect_tier_only_touches_matching_tier(session, raw_dir):
    tier1 = add_source(session, kind="rss", identifier="https://a/feed", tier=1)
    add_source(session, kind="x_account", identifier="@someone", tier=2)
    adapter = StubAdapter("rss", one_item())
    results = collect_tier(session, tier=1, registry={"rss": adapter}, raw_dir=raw_dir, now=NOW)
    assert [r.source_id for r in results] == [tier1.id]
    assert adapter.calls == 1


def test_collect_tier_skips_kinds_with_no_adapter(session, raw_dir):
    add_source(session, kind="unknown_kind", identifier="x", tier=1)
    results = collect_tier(session, tier=1, registry={}, raw_dir=raw_dir, now=NOW)
    assert results == []


def test_consecutive_failures_counts_only_the_recent_streak(session, raw_dir):
    source = add_source(session)
    for index, status in enumerate(["failed", "success", "failed", "failed"]):
        session.add(
            FetchRun(
                source_id=source.id,
                started_at=NOW - timedelta(hours=10 - index),
                finished_at=NOW - timedelta(hours=10 - index),
                status=status,
                items_found=0,
                items_new=0,
            )
        )
    session.flush()
    assert consecutive_failures(session, source.id) == 2


def test_backoff_blocks_retry_immediately_after_failure(session, raw_dir):
    source = add_source(session)
    session.add(
        FetchRun(
            source_id=source.id,
            started_at=NOW - timedelta(minutes=1),
            finished_at=NOW - timedelta(minutes=1),
            status="failed",
            items_found=0,
            items_new=0,
        )
    )
    session.flush()
    assert should_attempt(session, source.id, NOW) is False
    assert should_attempt(session, source.id, NOW + timedelta(minutes=30)) is True


def test_should_attempt_at_exact_backoff_boundary(session, raw_dir):
    """One failure backs off for exactly BASE_BACKOFF. The boundary is inclusive:
    one second before it, retry is still blocked; at the boundary itself, allowed."""
    source = add_source(session)
    session.add(
        FetchRun(
            source_id=source.id,
            started_at=NOW,
            finished_at=NOW,
            status="failed",
            items_found=0,
            items_new=0,
        )
    )
    session.flush()
    boundary = NOW + BASE_BACKOFF
    assert should_attempt(session, source.id, boundary - timedelta(seconds=1)) is False
    assert should_attempt(session, source.id, boundary) is True


def test_circuit_breaker_opens_after_five_consecutive_failures(session, raw_dir):
    source = add_source(session)
    for index in range(5):
        session.add(
            FetchRun(
                source_id=source.id,
                started_at=NOW - timedelta(days=10 - index),
                finished_at=NOW - timedelta(days=10 - index),
                status="failed",
                items_found=0,
                items_new=0,
            )
        )
    session.flush()
    assert should_attempt(session, source.id, NOW + timedelta(days=30)) is False


def test_force_overrides_the_circuit_breaker(session, raw_dir):
    source = add_source(session)
    for index in range(5):
        session.add(
            FetchRun(
                source_id=source.id,
                started_at=NOW - timedelta(days=10 - index),
                finished_at=NOW - timedelta(days=10 - index),
                status="failed",
                items_found=0,
                items_new=0,
            )
        )
    session.flush()
    adapter = StubAdapter("rss", one_item())
    results = collect_tier(
        session, tier=1, registry={"rss": adapter}, raw_dir=raw_dir, now=NOW, force=True
    )
    assert [r.status for r in results] == ["success"]


def test_source_health_reports_attention_state(session, raw_dir):
    source = add_source(session)
    session.flush()
    for index in range(5):
        session.add(
            FetchRun(
                source_id=source.id,
                started_at=NOW - timedelta(hours=5 - index),
                finished_at=NOW - timedelta(hours=5 - index),
                status="failed",
                items_found=0,
                items_new=0,
                error_text="boom",
            )
        )
    session.flush()
    statuses = source_health(session)
    assert len(statuses) == 1
    assert statuses[0].consecutive_failures == 5
    assert statuses[0].needs_attention is True
    assert statuses[0].last_status == "failed"


def test_collect_tier_isolates_non_adapter_error_and_continues_with_next_source(session, raw_dir):
    """Bulkhead proof: a non-AdapterError exception (KeyError) from one adapter must not
    abort collect_tier, and the failure must still be captured on the fetch_run."""
    bad = add_source(session, kind="rss", identifier="https://bad/feed", tier=1)
    good = add_source(session, kind="web_page", identifier="https://good/page", tier=1)
    registry = {
        "rss": StubAdapter("rss", error=KeyError("missing_field")),
        "web_page": StubAdapter("web_page", one_item()),
    }

    results = collect_tier(session, tier=1, registry=registry, raw_dir=raw_dir, now=NOW)

    assert [r.source_id for r in results] == [bad.id, good.id]
    assert results[0].status == "failed"
    assert results[0].error_text is not None
    assert "KeyError" in results[0].error_text
    assert results[1].status == "success"

    bad_run = session.execute(
        select(FetchRun).where(FetchRun.source_id == bad.id)
    ).scalars().one()
    assert bad_run.status == "failed"
    assert bad_run.error_text is not None
    assert "KeyError" in bad_run.error_text

    good_run = session.execute(
        select(FetchRun).where(FetchRun.source_id == good.id)
    ).scalars().one()
    assert good_run.status == "success"


def test_source_health_reports_error_text_and_item_count(session, raw_dir):
    good = add_source(session, kind="rss", identifier="https://a/feed", tier=1)
    bad = add_source(session, kind="web_page", identifier="https://b", tier=1)
    registry = {
        "rss": StubAdapter("rss", items=one_item()),
        "web_page": StubAdapter("web_page", error=AdapterError("upstream exploded")),
    }
    collect_tier(session, tier=1, registry=registry, raw_dir=raw_dir, now=NOW)

    health = {s.source_id: s for s in source_health(session)}
    assert health[good.id].item_count == 1
    assert health[good.id].error_text is None
    assert health[bad.id].item_count == 0
    assert "upstream exploded" in health[bad.id].error_text


def test_collect_tier_survives_a_poisoned_transaction_from_a_malformed_item(session, raw_dir):
    """A malformed item (url=None) passes NormalizedItem's dataclass with no runtime
    validation, then hits a genuine Postgres NOT NULL violation inside upsert_items.
    That violation aborts the database transaction. Without a savepoint around the
    fetch-and-store work, the flush that records the failed run would itself raise
    against the aborted transaction (PendingRollbackError), escaping collect_source
    and defeating the bulkhead. This proves the run is still recorded as failed and
    a subsequent source in the same collect_tier call still succeeds."""
    bad = add_source(session, kind="rss", identifier="https://bad/feed", tier=1)
    good = add_source(session, kind="web_page", identifier="https://good/page", tier=1)
    poisoned_item = NormalizedItem(external_id="1", url=None, title="t", content_text="body")
    registry = {
        "rss": StubAdapter("rss", [poisoned_item]),
        "web_page": StubAdapter("web_page", one_item()),
    }

    results = collect_tier(session, tier=1, registry=registry, raw_dir=raw_dir, now=NOW)

    assert [r.source_id for r in results] == [bad.id, good.id]
    assert results[0].status == "failed"
    assert results[0].error_text is not None
    assert results[1].status == "success"

    bad_run = session.execute(
        select(FetchRun).where(FetchRun.source_id == bad.id)
    ).scalars().one()
    assert bad_run.status == "failed"
    assert bad_run.error_text is not None

    good_run = session.execute(
        select(FetchRun).where(FetchRun.source_id == good.id)
    ).scalars().one()
    assert good_run.status == "success"
