"""Password verification service — OTP codes and reset links."""
from __future__ import annotations

import logging
import os
import random
import secrets
import string
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from src.services.email_service import send_otp_email, send_reset_link_email

_log = logging.getLogger(__name__)

_FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

_PURPOSE_LABELS = {
    "FIRST_LOGIN":       "première connexion",
    "VOLUNTARY_CHANGE":  "changement volontaire",
    "FORGOT_PASSWORD":   "réinitialisation",
}

_DEMO_OTP_CODES: dict[tuple[str, str], tuple[str, datetime]] = {}
_DEMO_RESET_TOKENS: dict[str, tuple[str, datetime]] = {}


def generate_otp(db: Session, user, purpose: str) -> str:
    """Generate and email a 6-digit OTP. Returns the code (for testing only)."""
    from src.storage.orm_models_password_verification import PasswordVerificationORM

    # Invalidate any existing unused OTPs for this user + purpose
    existing = (
        db.query(PasswordVerificationORM)
        .filter(
            PasswordVerificationORM.user_id == user.id,
            PasswordVerificationORM.purpose == purpose,
            PasswordVerificationORM.used.is_(False),
        )
        .all()
    )
    for pv in existing:
        pv.used = True

    code = "".join(random.choices(string.digits, k=6))
    pv = PasswordVerificationORM(
        user_id=user.id,
        verification_type="OTP",
        code_or_token=code,
        purpose=purpose,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db.add(pv)

    purpose_label = _PURPOSE_LABELS.get(purpose, purpose)
    send_otp_email(user.email, code, purpose_label)
    _log.info("OTP generated for %s (purpose=%s)", user.email, purpose)
    return code


def generate_demo_otp(email: str, purpose: str) -> str:
    """Generate an OTP for demo accounts without touching the database."""
    code = "".join(random.choices(string.digits, k=6))
    _DEMO_OTP_CODES[(email, purpose)] = (
        code,
        datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    purpose_label = _PURPOSE_LABELS.get(purpose, purpose)
    send_otp_email(email, code, purpose_label)
    _log.info("Demo OTP generated for %s (purpose=%s)", email, purpose)
    return code


def generate_reset_link(db: Session, user, purpose: str) -> str:
    """Generate and email a secure reset link. Returns the full URL."""
    from src.storage.orm_models_password_verification import PasswordVerificationORM

    # Invalidate existing unused tokens
    existing = (
        db.query(PasswordVerificationORM)
        .filter(
            PasswordVerificationORM.user_id == user.id,
            PasswordVerificationORM.purpose == purpose,
            PasswordVerificationORM.used.is_(False),
        )
        .all()
    )
    for pv in existing:
        pv.used = True

    token = secrets.token_urlsafe(48)  # 64 chars of URL-safe base64
    pv = PasswordVerificationORM(
        user_id=user.id,
        verification_type="LINK",
        code_or_token=token,
        purpose=purpose,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(pv)

    link = f"{_FRONTEND_URL}/reset-password?token={token}"
    send_reset_link_email(user.email, link)
    _log.info("Reset link generated for %s (purpose=%s)", user.email, purpose)
    return link


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


def verify_otp(db: Session, user_id: UUID, code: str) -> bool:
    """Return True and mark used if the OTP is valid and not expired."""
    from src.storage.orm_models_password_verification import PasswordVerificationORM

    now = datetime.now(timezone.utc)
    pv = (
        db.query(PasswordVerificationORM)
        .filter(
            PasswordVerificationORM.user_id == user_id,
            PasswordVerificationORM.verification_type == "OTP",
            PasswordVerificationORM.code_or_token == code,
            PasswordVerificationORM.used.is_(False),
            PasswordVerificationORM.expires_at > now,
        )
        .first()
    )
    if not pv:
        return False
    pv.used = True
    return True


def verify_demo_otp(email: str, code: str) -> bool:
    """Return True and mark used if a demo OTP is valid and not expired."""
    now = datetime.now(timezone.utc)
    for (stored_email, purpose), (stored_code, expires_at) in list(_DEMO_OTP_CODES.items()):
        if stored_email != email:
            continue
        if expires_at <= now:
            _DEMO_OTP_CODES.pop((stored_email, purpose), None)
            continue
        if stored_code == code:
            _DEMO_OTP_CODES.pop((stored_email, purpose), None)
            return True
    return False


def verify_reset_token(db: Session, token: str):
    """Return the associated User if the reset token is valid; else None."""
    from src.storage.orm_models_password_verification import PasswordVerificationORM
    from src.storage.orm_models_users import UserORM

    now = datetime.now(timezone.utc)
    pv = (
        db.query(PasswordVerificationORM)
        .filter(
            PasswordVerificationORM.verification_type == "LINK",
            PasswordVerificationORM.code_or_token == token,
            PasswordVerificationORM.used.is_(False),
            PasswordVerificationORM.expires_at > now,
        )
        .first()
    )
    if not pv:
        return None
    pv.used = True
    return db.get(UserORM, pv.user_id)


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
