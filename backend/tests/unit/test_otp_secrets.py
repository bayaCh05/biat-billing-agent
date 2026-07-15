"""Unit tests — Fix 5 (security audit): OTP generation must use the
`secrets` CSPRNG, never `random.choices()` (predictable, brute-forceable
seed — unacceptable for a 6-digit auth code).

Covers the only OTP-generation site actually wired to api/routers/auth.py:
src/storage/documents/service_bridge.py::generate_otp_native (Mongo-native).
The SQLAlchemy-based generate_otp/generate_demo_otp in
password_verification_service.py that used to be tested here were dead code
(zero callers after the Mongo migration); the whole module (including its
demo-account reset-link functions) was deleted once demo accounts were
removed from the login path (see CLAUDE.md "Section 1 — demo accounts").
"""
from __future__ import annotations

import asyncio
import re
import secrets as _secrets_mod
from unittest.mock import AsyncMock, MagicMock, patch

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
