"""Unit tests — Fix 4 (security audit): GET /security/summary must never
hardcode tampered_entries_count. It must reflect the real, merged
SQLite+Mongo HMAC integrity result from
api.routers.audit.compute_integrity_summary(), the same function backing
GET /audit/verify-integrity.

No async test plugin (pytest-asyncio/anyio) is installed in this repo's venv
today, so async code under test is driven with asyncio.run() from plain sync
test functions, matching the rest of this unit suite's conventions (see
CLAUDE.md — mock everything, no real event loop plumbing needed).
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET", "test-secret-for-security-summary-padding")

from api.routers.audit import compute_integrity_summary
from api.routers.security import security_summary
from api.security.audit_integrity import compute_row_hash, verify_row_status


def _fake_row(
    action: str, row_hash: str | None,
    rebaseline_hash: str | None = None, rebaselined_at=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id="log-1",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        user_id="user-1",
        action=action,
        resource_type="Invoice",
        resource_id="inv-1",
        status="SUCCESS",
        ip_address="127.0.0.1",
        row_hash=row_hash,
        rebaseline_hash=rebaseline_hash,
        rebaselined_at=rebaselined_at,
    )


def _session_with_rows(rows):
    session = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = rows
    return session


class TestComputeIntegritySummary:
    """Direct checks on the shared merge function."""

    def test_tampered_row_is_detected(self):
        valid_row = _fake_row("LOGIN_SUCCESS", None)
        valid_row.row_hash = compute_row_hash(valid_row)
        tampered_row = _fake_row("INVOICE_UPLOADED", "not-the-real-hash")

        session = _session_with_rows([valid_row, tampered_row])

        with patch(
            "src.storage.documents.service_bridge.verify_integrity_native",
            new=AsyncMock(return_value=None),
        ):
            result = asyncio.run(compute_integrity_summary(session))

        assert result["tampered_count"] == 1
        assert result["tampered_entries"][0]["id"] == "log-1"
        assert "altérée" in result["message"]
        session.commit.assert_called_once()

    def test_no_tampering_reports_zero(self):
        valid_row = _fake_row("LOGIN_SUCCESS", None)
        valid_row.row_hash = compute_row_hash(valid_row)
        session = _session_with_rows([valid_row])

        with patch(
            "src.storage.documents.service_bridge.verify_integrity_native",
            new=AsyncMock(return_value=None),
        ):
            result = asyncio.run(compute_integrity_summary(session))

        assert result["tampered_count"] == 0

    def test_mongo_side_tampering_is_merged_in(self):
        valid_row = _fake_row("LOGIN_SUCCESS", None)
        valid_row.row_hash = compute_row_hash(valid_row)
        session = _session_with_rows([valid_row])

        mongo_result = {
            "total_checked": 1,
            "valid": 0,
            "null_hash_count": 0,
            "tampered_count": 1,
            "tampered_entries": [{"id": "mongo-log-1", "created_at": "", "action": "AI_EXTRACT"}],
        }
        with patch(
            "src.storage.documents.service_bridge.verify_integrity_native",
            new=AsyncMock(return_value=mongo_result),
        ):
            result = asyncio.run(compute_integrity_summary(session))

        assert result["tampered_count"] == 1
        assert result["tampered_entries"][0]["id"] == "mongo-log-1"

    def test_rebaselined_row_is_not_counted_as_tampered(self):
        """A row whose row_hash no longer verifies (secret rotation) but whose
        rebaseline_hash does must be reported separately, never as tampered —
        see scripts/rebaseline_audit_hmac.py and docs/audit_hmac_incident.md."""
        row = _fake_row("LOGIN_SUCCESS", "stale-pre-rotation-hash")
        row.rebaseline_hash = compute_row_hash(row)
        row.rebaselined_at = datetime(2026, 7, 15, tzinfo=timezone.utc)
        session = _session_with_rows([row])

        with patch(
            "src.storage.documents.service_bridge.verify_integrity_native",
            new=AsyncMock(return_value=None),
        ):
            result = asyncio.run(compute_integrity_summary(session))

        assert result["tampered_count"] == 0
        assert result["rebaselined_count"] == 1
        assert result["rebaselined_entries"][0]["id"] == "log-1"
        assert "rebaselined" in result["message"]

    def test_row_hash_and_rebaseline_hash_both_fail_is_still_tampered(self):
        row = _fake_row("LOGIN_SUCCESS", "stale-hash", rebaseline_hash="also-wrong-hash")
        session = _session_with_rows([row])

        with patch(
            "src.storage.documents.service_bridge.verify_integrity_native",
            new=AsyncMock(return_value=None),
        ):
            result = asyncio.run(compute_integrity_summary(session))

        assert result["tampered_count"] == 1
        assert result["rebaselined_count"] == 0


class TestVerifyRowStatus:
    def test_original_hash_still_valid(self):
        row = _fake_row("LOGIN_SUCCESS", None)
        row.row_hash = compute_row_hash(row)
        assert verify_row_status(row) == "original"

    def test_rebaseline_hash_valid_when_row_hash_stale(self):
        row = _fake_row("LOGIN_SUCCESS", "stale-hash")
        row.rebaseline_hash = compute_row_hash(row)
        assert verify_row_status(row) == "rebaselined"

    def test_neither_matches_is_failed(self):
        row = _fake_row("LOGIN_SUCCESS", "stale-hash", rebaseline_hash="also-stale")
        assert verify_row_status(row) == "failed"

    def test_no_row_hash_at_all_is_failed(self):
        row = _fake_row("LOGIN_SUCCESS", None)
        assert verify_row_status(row) == "failed"


class TestSecuritySummaryWiring:
    """The /security/summary route must surface the real count, on both
    the Mongo-native and SQLite-fallback response paths — not a hardcoded 0."""

    def test_mongo_path_uses_real_tampered_count(self):
        mongo_dict = {
            "total_logins_today": 0,
            "tampered_entries_count": 0,  # what security_summary_mongo() would hand back
        }
        with patch(
            "api.routers.security.compute_integrity_summary",
            new=AsyncMock(return_value={"tampered_count": 7, "rebaselined_count": 2}),
        ), patch(
            "src.storage.documents.service_bridge.security_summary_mongo",
            new=AsyncMock(return_value=dict(mongo_dict)),
        ):
            result = asyncio.run(security_summary(_={"role": "Admin"}, session=MagicMock()))

        assert result["tampered_entries_count"] == 7
        assert result["rebaselined_entries_count"] == 2

    def test_sqlite_fallback_path_uses_real_tampered_count(self):
        session = MagicMock()
        # Every session.execute(...).scalar() call (login/upload counters) → 0
        session.scalar.return_value = 0
        # Every session.execute(...).scalars().all() call (locked/suspicious users) → []
        session.execute.return_value.scalars.return_value.all.return_value = []
        session.execute.return_value.scalar_one_or_none.return_value = None

        with patch(
            "api.routers.security.compute_integrity_summary",
            new=AsyncMock(return_value={"tampered_count": 5, "rebaselined_count": 1}),
        ), patch(
            "src.storage.documents.service_bridge.security_summary_mongo",
            new=AsyncMock(return_value=None),
        ):
            result = asyncio.run(security_summary(_={"role": "Admin"}, session=session))

        assert result["tampered_entries_count"] == 5
        assert result["rebaselined_entries_count"] == 1
