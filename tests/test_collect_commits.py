import pytest
from sqlalchemy import select

from test_collect import NOW, StubAdapter, add_source, one_item

from reachstore.collect import collect_tier
from reachstore.models import FetchRun


def test_each_source_is_committed_before_the_next_one_starts(session, raw_dir, monkeypatch):
    """Commits must interleave with fetches, not all land at the end.

    This is what makes the UI's progress view progressive rather than a long
    pause followed by everything appearing at once.
    """
    add_source(session, kind="rss", identifier="https://a/feed", tier=1)
    add_source(session, kind="web_page", identifier="https://b", tier=1)

    events: list[str] = []
    real_commit = session.commit

    def spy_commit():
        events.append("commit")
        real_commit()

    monkeypatch.setattr(session, "commit", spy_commit)

    class RecordingAdapter:
        def __init__(self, kind):
            self.kind = kind
            self.tier = 1

        def fetch(self, identifier, since):
            events.append(f"fetch:{identifier}")
            return one_item()

    registry = {"rss": RecordingAdapter("rss"), "web_page": RecordingAdapter("web_page")}
    collect_tier(session, tier=1, registry=registry, raw_dir=raw_dir, now=NOW)

    assert events == [
        "fetch:https://a/feed",
        "commit",
        "fetch:https://b",
        "commit",
    ]


def test_a_failing_commit_does_not_abort_the_rest_of_the_tier(session, raw_dir, monkeypatch):
    """The bulkhead has to cover the commit too.

    `collect_source` never raises, but the commit that now follows it can --
    a dropped connection, a deadlock. Letting that escape would abort the
    whole tier, which is precisely what per-source isolation exists to stop.
    """
    add_source(session, kind="rss", identifier="https://a/feed", tier=1)
    add_source(session, kind="web_page", identifier="https://b", tier=1)
    add_source(session, kind="github_repo", identifier="o/r", tier=1)

    real_commit = session.commit
    attempts = {"n": 0}

    def flaky_commit():
        attempts["n"] += 1
        if attempts["n"] == 2:
            raise RuntimeError("connection lost")
        real_commit()

    monkeypatch.setattr(session, "commit", flaky_commit)

    registry = {
        "rss": StubAdapter("rss", items=one_item()),
        "web_page": StubAdapter("web_page", items=one_item()),
        "github_repo": StubAdapter("github_repo", items=one_item()),
    }
    results = collect_tier(session, tier=1, registry=registry, raw_dir=raw_dir, now=NOW)

    assert len(results) == 3, "a failed commit stopped the tier"
    assert attempts["n"] == 3


def test_a_failing_commit_produces_a_failed_result_not_a_stale_success(
    session, raw_dir, monkeypatch
):
    """A commit that fails and rolls back must not report the discarded work as done.

    `collect_source` appends its CollectResult to `results` before the commit
    runs. If the commit then fails, that appended result still reads
    status="success" with item counts, for work the rollback just discarded.
    The caller (the CLI's summary line, and its all-sources-failed exit path)
    acts on that result, so a swallowed commit failure would silently report
    success -- and exit 0 -- for a run that persisted nothing.
    """
    add_source(session, kind="rss", identifier="https://a/feed", tier=1)

    def always_raise():
        raise RuntimeError("connection lost")

    monkeypatch.setattr(session, "commit", always_raise)

    registry = {"rss": StubAdapter("rss", items=one_item())}
    results = collect_tier(session, tier=1, registry=registry, raw_dir=raw_dir, now=NOW)

    assert len(results) == 1
    result = results[0]
    assert result.status == "failed"
    assert result.items_found == 0
    assert result.items_new == 0
    assert result.error_text is not None and "commit" in result.error_text


def test_a_failing_commit_rolls_back_the_session(session, raw_dir, monkeypatch):
    """The rollback is the load-bearing half of the commit-failure handler.

    It is what leaves the session usable for the next source after a real
    failure. A test that only checks downstream effects (the tier keeps
    running, the result reads "failed") can stay green even if
    `session.rollback()` were replaced with `pass`, since nothing else in
    this code path happens to require the transaction to actually be reset.
    This pins the rollback call directly.

    The first commit is left to succeed for real, exactly as in
    `test_a_failing_commit_does_not_abort_the_rest_of_the_tier`: only the
    second commit fails, so the sources flushed before `collect_tier` ever
    ran stay durably committed and the second source's row lookups don't
    trip over a rollback that undid them.
    """
    add_source(session, kind="rss", identifier="https://a/feed", tier=1)
    add_source(session, kind="web_page", identifier="https://b", tier=1)

    real_commit = session.commit
    attempts = {"n": 0}

    def flaky_commit():
        attempts["n"] += 1
        if attempts["n"] == 2:
            raise RuntimeError("connection lost")
        real_commit()

    events: list[str] = []
    real_rollback = session.rollback

    def spy_rollback():
        events.append("rollback")
        real_rollback()

    monkeypatch.setattr(session, "commit", flaky_commit)
    monkeypatch.setattr(session, "rollback", spy_rollback)

    registry = {
        "rss": StubAdapter("rss", items=one_item()),
        "web_page": StubAdapter("web_page", items=one_item()),
    }
    collect_tier(session, tier=1, registry=registry, raw_dir=raw_dir, now=NOW)

    assert events == ["rollback"]


def test_a_crash_mid_source_leaves_no_committed_running_row(session, raw_dir):
    """A committed `running` row would silently reset the circuit breaker.

    `consecutive_failures` scans newest-first and stops at the first
    non-"failed" status, so a single stale `running` sitting on top of a long
    failure streak reports zero failures and reopens a source that has been
    broken for days. Per-source commit must never expose that state.

    KeyboardInterrupt is a BaseException, so `collect_source`'s `except
    Exception` bulkhead does not catch it -- it propagates exactly as a real
    Ctrl-C or process kill would, mid-source, after the "running" row was
    flushed but before it reached a terminal status.

    This test already passed before per-source commits existed, since
    nothing was committed at all. It stays in the suite as a guard against a
    future refactor -- e.g. moving the commit into a `finally`, or widening
    the handler to a bare `except BaseException` -- that would start
    committing a row still sitting at "running".
    """
    add_source(session, kind="rss", identifier="https://a/feed", tier=1)

    class CrashingAdapter:
        kind = "rss"
        tier = 1

        def fetch(self, identifier, since):
            raise KeyboardInterrupt("simulated process death")

    with pytest.raises(KeyboardInterrupt):
        collect_tier(
            session,
            tier=1,
            registry={"rss": CrashingAdapter()},
            raw_dir=raw_dir,
            now=NOW,
        )

    # Discard the uncommitted work, exactly as a crashed process would.
    session.rollback()
    statuses = session.execute(select(FetchRun.status)).scalars().all()
    assert "running" not in statuses
