"""Password verification service — demo-account reset links (in-memory, no DB).

The SQLAlchemy-backed OTP/reset-link functions that used to live here
(generate_otp, generate_demo_otp, generate_reset_link, verify_otp,
verify_reset_token, verify_demo_otp) had zero callers — the real OTP/reset
flow is Mongo-native (service_bridge.py::generate_otp_native/verify_otp_native
etc., wired from api/routers/auth.py). See CLAUDE.md "MongoDB Migration
Status". Only the demo-account functions below have no Mongo equivalent
because they were never meant to touch a database at all.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from src.services.email_service import send_reset_link_email

_log = logging.getLogger(__name__)

_FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

_DEMO_RESET_TOKENS: dict[str, tuple[str, datetime]] = {}


def generate_demo_reset_link(email: str, purpose: str) -> str:
    """Generate a reset link for demo accounts without a database row."""
    token = secrets.token_urlsafe(48)
    _DEMO_RESET_TOKENS[token] = (
        email,
        datetime.now(timezone.utc) + timedelta(hours=1),
    )
    link = f"{_FRONTEND_URL}/reset-password?token={token}"
    send_reset_link_email(email, link)
    _log.info("Demo reset link generated for %s (purpose=%s)", email, purpose)
    return link


def verify_demo_reset_token(token: str) -> str | None:
    """Return the demo email if the reset token is valid; else None."""
    now = datetime.now(timezone.utc)
    item = _DEMO_RESET_TOKENS.get(token)
    if not item:
        return None
    email, expires_at = item
    if expires_at <= now:
        _DEMO_RESET_TOKENS.pop(token, None)
        return None
    _DEMO_RESET_TOKENS.pop(token, None)
    return email
