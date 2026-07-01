"""HMAC-based audit log tamper detection."""
from __future__ import annotations

import hashlib
import hmac
import os

HMAC_SECRET = os.getenv("AUDIT_HMAC_SECRET", "")


def _get_secret() -> bytes:
    s = HMAC_SECRET or os.getenv("JWT_SECRET", "")  # fallback for dev
    return s.encode()


def compute_row_hash(log) -> str:
    """Compute HMAC-SHA256 for an AuditLogORM row."""
    created = log.created_at.isoformat() if log.created_at else ""
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
