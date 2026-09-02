import pytest

from reachstore.api.app import assert_loopback


def test_loopback_hosts_are_allowed():
    for host in ("127.0.0.1", "localhost", "::1"):
        assert_loopback(host, allow_nonlocal=False)


def test_non_loopback_host_is_refused():
    with pytest.raises(RuntimeError) as exc:
        assert_loopback("0.0.0.0", allow_nonlocal=False)
    assert "REACHSTORE_ALLOW_NONLOCAL" in str(exc.value)


def test_non_loopback_host_allowed_with_explicit_override():
    assert_loopback("0.0.0.0", allow_nonlocal=True)
