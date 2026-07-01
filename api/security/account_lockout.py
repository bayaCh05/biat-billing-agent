"""Account lockout after repeated failed login attempts."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

MAX_ATTEMPTS = int(os.getenv("MAX_FAILED_LOGIN_ATTEMPTS", "5"))
LOCKOUT_MINUTES = int(os.getenv("ACCOUNT_LOCKOUT_MINUTES", "15"))


def check_locked(user) -> tuple[bool, int]:
    """Return (is_locked, remaining_minutes). Auto-unlocks if lockout expired."""
    locked_until = getattr(user, "locked_until", None)
    if not locked_until:
        return False, 0
    now = datetime.now(timezone.utc)
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    if locked_until > now:
        remaining = max(1, int((locked_until - now).total_seconds() // 60))
        return True, remaining
    # Lockout expired — auto-reset (caller must commit)
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_failed_login = None
    return False, 0


def record_failed(user, db: Session) -> int:
    """Increment failed counter, lock if threshold reached. Returns attempts count."""
    user.failed_login_attempts = (getattr(user, "failed_login_attempts", 0) or 0) + 1
    user.last_failed_login = datetime.now(timezone.utc)
    if user.failed_login_attempts >= MAX_ATTEMPTS:
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
    db.flush()
    return user.failed_login_attempts


def record_success(user, db: Session) -> None:
    """Reset failed counter on successful login."""
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_failed_login = None
    user.last_login_at = datetime.now(timezone.utc)
    db.flush()
