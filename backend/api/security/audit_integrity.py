"""HMAC-based audit log tamper detection."""
from __future__ import annotations

import hashlib
import hmac
import os

def _get_secret() -> bytes:
    # Read from env on every call — do NOT cache at module level.
    # The module may be imported before the shell sets JWT_SECRET, and a
    # stale module-level constant would cause every hash to use the wrong key.
    s = os.getenv("AUDIT_HMAC_SECRET", "").strip() or os.getenv("JWT_SECRET", "")
    return s.encode()


def compute_row_hash(log) -> str:
    """Compute HMAC-SHA256 for an AuditLogORM row."""
    if log.created_at:
        dt = log.created_at
        # Always strip timezone before isoformat — SQLite reads back naive datetimes,
        # so a timezone-aware isoformat ("+00:00") written at insert time produces a
        # different string and causes false "tampered" positives on every verification.
        if getattr(dt, "tzinfo", None) is not None:
            dt = dt.replace(tzinfo=None)
        created = dt.isoformat()
    else:
        created = ""
    payload = (
        f"{log.id}|"
        f"{created}|"
        f"{log.user_id or 'system'}|"
        f"{log.action}|"
        f"{log.resource_type or ''}|"
        f"{log.resource_id or ''}|"
        f"{log.status}|"
        f"{log.ip_address or ''}"
    )
    return hmac.new(
        _get_secret(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_row_hash(log) -> bool:
    """Return True if the stored row_hash matches the recomputed value."""
    expected = compute_row_hash(log)
    stored = getattr(log, "row_hash", None) or ""
    return hmac.compare_digest(expected, stored)
