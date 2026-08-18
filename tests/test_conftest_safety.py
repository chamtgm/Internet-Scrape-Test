"""F10: the `engine` fixture in conftest.py drops the schema at TEST_DATABASE_URL
with no check that it differs from DATABASE_URL or looks like a test database.
These tests exercise the extracted guard directly rather than the session-scoped
fixture itself, since the fixture runs once per test session and already backs
every other test in the suite.
"""

import pytest

from conftest import _guard_test_database


def test_guard_rejects_test_url_identical_to_primary_url():
    with pytest.raises(pytest.fail.Exception):
        _guard_test_database(
            "postgresql+psycopg://u:p@localhost/reachstore",
            "postgresql+psycopg://u:p@localhost/reachstore",
        )


def test_guard_rejects_database_name_not_ending_in_test():
    with pytest.raises(pytest.fail.Exception):
        _guard_test_database(
            "postgresql+psycopg://u:p@localhost/reachstore",
            "postgresql+psycopg://u:p@localhost/reachstore_primary",
        )


def test_guard_allows_a_genuine_test_database():
    # Must not raise.
    _guard_test_database(
        "postgresql+psycopg://u:p@localhost/reachstore_test",
        "postgresql+psycopg://u:p@localhost/reachstore",
    )
