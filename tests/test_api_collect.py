from datetime import UTC

from reachstore.api import collect_runner


def test_collect_accepts_and_reports_started(session, admin_client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        collect_runner, "run_collection", lambda tier, force: calls.append((tier, force))
    )
    response = admin_client.post("/api/collect", json={"tier": 1, "force": False})
    assert response.status_code == 202
    assert response.json()["started"] is True
    assert response.json()["tier"] == 1
    # TestClient runs background tasks before returning from the request.
    assert calls == [(1, False)]


def test_collect_rejects_a_second_run_while_one_is_in_flight(session, admin_client):
    # Claim the slot for real, the same way post_collect's own try_start()
    # call would for an in-flight run -- not by monkeypatching is_running,
    # which would pass even if the handler's guard were not atomic.
    assert collect_runner.try_start() is True
    response = admin_client.post("/api/collect", json={"tier": 1, "force": False})
    assert response.status_code == 409
    assert response.json()["started"] is False
    assert response.json()["reason"]


def test_collect_rejects_an_invalid_tier(session, admin_client):
    client = admin_client
    assert client.post("/api/collect", json={"tier": 0}).status_code == 422
    assert client.post("/api/collect", json={"tier": 9}).status_code == 422


def test_sources_endpoint_reports_whether_a_run_is_in_flight(session, admin_client, monkeypatch):
    client = admin_client
    assert client.get("/api/sources").json()["collecting"] is False
    monkeypatch.setattr(collect_runner, "is_running", lambda: True)
    assert client.get("/api/sources").json()["collecting"] is True


def test_the_runner_opens_its_own_session_and_always_clears_the_flag(
    session, raw_dir, monkeypatch
):
    """The background task must not reuse the request-scoped session.

    FastAPI background tasks run after the response is sent, by which point
    the request session is already closed. This also pins the flag lifecycle:
    a run that raises must not leave `is_running()` stuck True, which would
    disable the Collect button until the server restarts.
    """

    class FakeSession:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    fake = FakeSession()
    monkeypatch.setattr(collect_runner, "get_session_factory", lambda: (lambda: fake))
    monkeypatch.setattr(collect_runner, "raw_dir", lambda: raw_dir)

    seen = {}

    def fake_collect_tier(sess, **kwargs):
        seen["session"] = sess
        seen["tier"] = kwargs["tier"]
        seen["force"] = kwargs["force"]
        seen["now"] = kwargs["now"]
        seen["running_during"] = collect_runner.is_running()
        return []

    monkeypatch.setattr(collect_runner, "collect_tier", fake_collect_tier)
    # run_collection no longer claims the slot itself -- it trusts the
    # caller already did, the same way post_collect's try_start() call would.
    assert collect_runner.try_start() is True
    collect_runner.run_collection(tier=2, force=True)

    assert seen["session"] is fake
    assert seen["session"] is not session
    assert seen["tier"] == 2 and seen["force"] is True
    assert seen["now"].tzinfo is UTC
    assert seen["running_during"] is True
    assert fake.closed
    assert collect_runner.is_running() is False


def test_a_crashing_run_still_clears_the_flag(session, raw_dir, monkeypatch):
    class FakeSession:
        def close(self):
            pass

    monkeypatch.setattr(collect_runner, "get_session_factory", lambda: (lambda: FakeSession()))
    monkeypatch.setattr(collect_runner, "raw_dir", lambda: raw_dir)

    def boom(sess, **kwargs):
        raise RuntimeError("database gone")

    monkeypatch.setattr(collect_runner, "collect_tier", boom)
    assert collect_runner.try_start() is True
    collect_runner.run_collection(tier=1, force=False)  # must not raise
    assert collect_runner.is_running() is False


def test_a_session_close_that_raises_still_clears_the_flag(session, raw_dir, monkeypatch):
    """close() can itself raise -- a connection broken mid-transaction is
    exactly what the outage collect_tier's except clause guards against.
    Neither older fake session had a close() that could raise."""

    class FakeSession:
        def close(self):
            raise RuntimeError("connection already closed")

    monkeypatch.setattr(collect_runner, "get_session_factory", lambda: (lambda: FakeSession()))
    monkeypatch.setattr(collect_runner, "raw_dir", lambda: raw_dir)
    monkeypatch.setattr(collect_runner, "collect_tier", lambda sess, **kwargs: [])

    assert collect_runner.try_start() is True
    collect_runner.run_collection(tier=1, force=False)  # must not raise
    assert collect_runner.is_running() is False
