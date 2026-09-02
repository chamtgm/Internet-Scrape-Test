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


def run_collection(tier: int, force: bool) -> None:
    """Run one tier to completion. Never raises.

    Opens its own session: FastAPI background tasks run after the response has
    been sent, so the request-scoped session is already closed by then.

    The guard flag is per-process. This slice is single-worker by design;
    running uvicorn with multiple workers would give each its own copy and
    defeat the guard, which would then need a Postgres advisory lock instead.
    """
    global _running
    with _lock:
        if _running:
            return
        _running = True

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
    except Exception:
        # A background task that raises produces an unhandled-exception
        # traceback from the ASGI layer after the response has already been
        # sent, which no client ever sees. Log it here instead.
        log.exception("collection run failed for tier %s", tier)
    finally:
        session.close()
        with _lock:
            _running = False
