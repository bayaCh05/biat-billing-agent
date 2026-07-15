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
        # Normalise à la milliseconde — MongoDB tronque les µs (BSON Date = ms).
        # Garantit que le hash est identique quelle que soit la source (SQLite ou MongoDB).
        dt = dt.replace(microsecond=(dt.microsecond // 1000) * 1000)
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


def verify_row_status(log) -> str:
    """Three-way tamper status, aware of the rebaseline columns added for the
    2026-07-10 secret rotation (see docs/audit_hmac_incident.md):

    - "original"   : row_hash (computed at write time) still verifies — the
      normal case for any row written under the current secret.
    - "rebaselined": row_hash no longer verifies (secret was rotated since),
      but rebaseline_hash — computed once, after the rotation, and stored
      alongside row_hash without ever overwriting it — does. The row is
      real and its rebaseline is on record; it is deliberately NOT reported
      as "tampered".
    - "failed"     : neither matches — either row_hash is unset and no
      rebaseline was ever computed, or the row genuinely fails both checks.
    """
    if verify_row_hash(log):
        return "original"
    rebaseline_hash = getattr(log, "rebaseline_hash", None)
    if rebaseline_hash and hmac.compare_digest(compute_row_hash(log), rebaseline_hash):
        return "rebaselined"
    return "failed"


# ── Mongo-native equivalents ───────────────────────────────────────────────────
# compute_row_hash()/verify_row_hash() above read attributes (log.id, log.action,
# ...) so they already work unchanged against any duck-typed object — including
# raw audit_logs documents from Mongo (Phase 4 made the HMAC payload source-agnostic
# by truncating datetimes to millisecond precision). These two helpers are just a
# dict → attribute-namespace adapter so the SAME formula can be applied to a Mongo
# document (`_id` instead of `id`, everything else identical) without ANY change to
# compute_row_hash() itself. There is no separate "Mongo hash chain" — this is a
# per-row HMAC exactly like SQLite's, not a chain (no row links to a previous row's
# hash), so there is nothing to "re-anchor" across the SQLite/Mongo boundary today.

def _hashable_from_doc(doc: dict):
    from types import SimpleNamespace
    return SimpleNamespace(
        id=doc.get("_id") or doc.get("id"),
        created_at=doc.get("created_at"),
        user_id=doc.get("user_id"),
        action=doc.get("action"),
        resource_type=doc.get("resource_type"),
        resource_id=doc.get("resource_id"),
        status=doc.get("status"),
        ip_address=doc.get("ip_address"),
    )


def compute_row_hash_from_doc(doc: dict) -> str:
    """Mongo-native equivalent of compute_row_hash() for a raw audit_logs dict."""
    return compute_row_hash(_hashable_from_doc(doc))


def verify_row_hash_from_doc(doc: dict) -> bool:
    """Mongo-native equivalent of verify_row_hash() for a raw audit_logs dict."""
    expected = compute_row_hash_from_doc(doc)
    stored = doc.get("row_hash") or ""
    return hmac.compare_digest(expected, stored)
