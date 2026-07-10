"""Unit tests — LDAP_BIND_PASSWORD hardcoded fallback removal (post-audit
follow-up: same shape as the JWT_SECRET fix).

ldap_service.py is only imported lazily (on the first LDAP login attempt),
so the fail-fast check lives in api/main.py::_startup() instead of at
ldap_service.py's import time — this test exercises that startup check
directly, with the DB-seeding side effects mocked out (unrelated to what's
being tested here).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from api.main import _startup


@pytest.fixture(autouse=True)
def _mock_demo_seeding():
    """_startup() also seeds demo accounts into the real configured DB —
    irrelevant to this test and not something a unit test should touch."""
    with patch("api.deps.get_session_ctx", side_effect=RuntimeError("no db in this test")):
        yield


class TestLdapBindPasswordStartupValidation:
    def test_raises_when_ldap_mode_and_password_missing(self, monkeypatch):
        monkeypatch.setenv("AUTH_MODE", "ldap")
        monkeypatch.setenv("LDAP_BIND_PASSWORD", "")
        with pytest.raises(RuntimeError, match="LDAP_BIND_PASSWORD"):
            _startup()

    def test_raises_when_hybrid_mode_and_password_missing(self, monkeypatch):
        monkeypatch.setenv("AUTH_MODE", "hybrid")
        monkeypatch.delenv("LDAP_BIND_PASSWORD", raising=False)
        with pytest.raises(RuntimeError, match="LDAP_BIND_PASSWORD"):
            _startup()

    def test_does_not_raise_when_ldap_mode_and_password_set(self, monkeypatch):
        monkeypatch.setenv("AUTH_MODE", "ldap")
        monkeypatch.setenv("LDAP_BIND_PASSWORD", "a-real-password")
        _startup()  # must not raise

    def test_does_not_require_password_when_auth_mode_local(self, monkeypatch):
        monkeypatch.setenv("AUTH_MODE", "local")
        monkeypatch.delenv("LDAP_BIND_PASSWORD", raising=False)
        _startup()  # must not raise — LDAP is never used in this mode
