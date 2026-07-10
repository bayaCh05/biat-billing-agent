"""Unit tests — Fix 5 (security audit): OTP generation must use the
`secrets` CSPRNG, never `random.choices()` (predictable, brute-forceable
seed — unacceptable for a 6-digit auth code).

Covers all three OTP-generation sites found in the codebase:
- src/storage/documents/service_bridge.py::generate_otp_native (Mongo-native,
  the one actually wired to api/routers/auth.py today)
- src/services/password_verification_service.py::generate_otp (SQLite path)
- src/services/password_verification_service.py::generate_demo_otp (demo
  accounts, no DB) — both currently dead code (no callers left after the
  Mongo migration), fixed anyway since they're the same vulnerable pattern.
"""
from __future__ import annotations

import asyncio
import re
import secrets as _secrets_mod
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.password_verification_service import generate_demo_otp, generate_otp
from src.storage.documents.service_bridge import generate_otp_native

_SIX_DIGITS = re.compile(r"^\d{6}$")


class TestOTPUsesSecretsNotRandom:
    def test_generate_otp_native_uses_secrets_choice(self):
        user_doc = MagicMock(id="user-1", email="a@biat-it.tn")
        coll = MagicMock()
        coll.update_many = AsyncMock()
        coll.insert_one = AsyncMock()

        with (
            patch(
                "src.storage.documents.password_verification.PasswordVerificationDocument.get_pymongo_collection",
                return_value=coll,
            ),
            patch("src.services.email_service.send_otp_email") as mock_send,
            patch("secrets.choice", wraps=_secrets_mod.choice) as spy_choice,
        ):
            code = asyncio.run(generate_otp_native(user_doc, "FIRST_LOGIN"))

        assert _SIX_DIGITS.match(code)
        assert spy_choice.call_count == 6
        mock_send.assert_called_once()
        coll.insert_one.assert_awaited_once()

    def test_generate_otp_sql_uses_secrets_choice(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        user = MagicMock(id="user-1", email="a@biat-it.tn")

        with (
            patch("src.services.password_verification_service.send_otp_email") as mock_send,
            patch("secrets.choice", wraps=_secrets_mod.choice) as spy_choice,
        ):
            code = generate_otp(db, user, "FIRST_LOGIN")

        assert _SIX_DIGITS.match(code)
        assert spy_choice.call_count == 6
        mock_send.assert_called_once()
        db.add.assert_called_once()

    def test_generate_demo_otp_uses_secrets_choice(self):
        with (
            patch("src.services.password_verification_service.send_otp_email") as mock_send,
            patch("secrets.choice", wraps=_secrets_mod.choice) as spy_choice,
        ):
            code = generate_demo_otp("demo@biat-it.tn", "FIRST_LOGIN")

        assert _SIX_DIGITS.match(code)
        assert spy_choice.call_count == 6
        mock_send.assert_called_once()

    def test_password_verification_service_no_longer_imports_random(self):
        import src.services.password_verification_service as mod

        assert not hasattr(mod, "random")
