"""Export integrity signature service — SHA-256 hash for BCT compliance reports.

Compliance: PCE Tunisien - BCT Circulaire 2025-13
All computation is local — no data transmitted to external services.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone


def generate_export_signature(file_content: bytes, metadata: dict) -> dict:
    """Compute SHA-256 hash of file_content and return a signed metadata block."""
    digest = hashlib.sha256(file_content).hexdigest()
    return {
        "algorithm":               "SHA-256",
        "hash":                    digest,
        "file_size_bytes":         len(file_content),
        "generated_at":            datetime.now(timezone.utc).isoformat(),
        "generated_by":            metadata.get("user_email", "system"),
        "period":                  metadata.get("period", ""),
        "record_count":            metadata.get("record_count", 0),
        "total_export_amount_tnd": metadata.get("total_amount_tnd", 0.0),
        "overdue_count":           metadata.get("overdue_count", 0),
        "system":                  "BIAT IT Billing Agent v1.0",
        "compliance":              "BCT Circulaire 2025-13 — Rapatriement exports",
    }


def verify_export_signature(file_content: bytes, signature: dict) -> bool:
    """Recompute SHA-256 and compare with the stored hash. Returns True if intact."""
    recomputed = hashlib.sha256(file_content).hexdigest()
    return recomputed == signature.get("hash", "")
