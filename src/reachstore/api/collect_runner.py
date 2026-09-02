from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime

from reachstore.adapters.base import HttpxFetcher, SubprocessRunner
from reachstore.adapters.registry import build_registry
from reachstore.api.deps import get_session_factory, raw_dir
from reachstore.collect import collect_tier

log = logging.getLogger(__name__)

_lock = threading.Lock()
_running = False


def is_running() -> bool:
    """Whether a collection run is in flight in this process.

    This is the frontend's completion signal. It cannot be inferred from
    fetch_run status instead: `collect_tier` only ever commits terminal
    statuses (see Task 4), so a reader never observes a "running" row.
    """
    return _running


def try_start() -> bool:
    """Atomically claim the single run slot. True if claimed, False if a run
    is already in flight.

    This must be called synchronously by the request handler, before the
    background task is scheduled -- not from inside `run_collection` itself.
    A FastAPI background task runs after the response has already been sent,
    so claiming the flag there leaves a window (the rest of the handler,
    response serialisation, the socket write) during which a second request's
    `is_running()` check would still see False and also report `started:
    True`, even though only one of the two runs would actually happen. The
    409 this backs is only truthful if the claim happens here.

    The flag stays held from this claim until `run_collection` finishes, not
    just while `collect_tier` is executing. If Starlette never runs the
    scheduled task -- e.g. the client disconnects between the response and
    dispatch, or the process shuts down in that window -- the flag leaks
    until the process restarts. That is accepted deliberately: a rare,
    restart-recoverable stuck button is better than a common, silent failure
    to collect while reporting success. No staleness timeout is added for
    this -- out of scope for a single-user localhost app.
    """
    global _running
    with _lock:
        if _running:
            return False
        _running = True
        return True


def run_collection(tier: int, force: bool) -> None:
    """Run one tier to completion. Never raises.

    Assumes the caller has already claimed the run slot via `try_start()` --
    this function only clears it, it does not claim it. Opens its own
    session: FastAPI background tasks run after the response has been sent,
    so the request-scoped session is already closed by then.

    The guard flag is per-process. This slice is single-worker by design;
    running uvicorn with multiple workers would give each its own copy and
    defeat the guard, which would then need a Postgres advisory lock instead.
    """
    global _running
    if not _running:
        # Unreachable via the API: post_collect calls try_start() before
        # scheduling this as a background task. A direct call without that
        # claim is a caller bug -- log it and bail rather than run unguarded.
        log.warning("run_collection called for tier %s without a claimed slot", tier)
        return

    try:
        # get_session_factory() can raise (e.g. a missing/malformed
        # DATABASE_URL reaching create_engine), and lru_cache does not cache
        # exceptions, so it would raise on every call forever. That must
        # still clear the flag, so session acquisition lives inside this
        # try, not before it.
        session = get_session_factory()()
        try:
            collect_tier(
                session,
                tier=tier,
                registry=build_registry(HttpxFetcher(), SubprocessRunner()),
                raw_dir=raw_dir(),
                now=datetime.now(UTC),
                force=force,
            )
        finally:
            # session.close() can itself raise (a connection broken mid-
            # transaction -- exactly what the outage below might leave
            # behind), so it must not sit after the except/finally that
            # clears the flag.
            session.close()
    except Exception:
        # A background task that raises produces an unhandled-exception
        # traceback from the ASGI layer after the response has already been
        # sent, which no client ever sees. Log it here instead.
        log.exception("collection run failed for tier %s", tier)
    finally:
        with _lock:
            _running = False
