"""Unit tests — service_bridge.py audit functions (Tier 1, sub-batch 2 of the
test-coverage scoping plan: auth writes done, audit next, then invoices).

Covers list_audit_logs_mongo, resource_history_mongo, log_audit_event_native,
_create_audit_log_native, and verify_integrity_native — none had direct
tests before (verify_integrity_native was only ever mocked away as a
dependency in test_security_integrity_summary.py, never exercised for its
own HMAC-verification logic).
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET", "test-secret-for-service-bridge-audit-padding")

from api.security.audit_integrity import compute_row_hash_from_doc
from src.storage.documents.service_bridge import (
    _create_audit_log_native,
    list_audit_logs_mongo,
    log_audit_event_native,
    resource_history_mongo,
    verify_integrity_native,
)


def _run(coro):
    return asyncio.run(coro)


def _find_chain(return_value):
    chain = MagicMock()
    chain.sort.return_value = chain
    chain.skip.return_value = chain
    chain.limit.return_value = chain
    chain.to_list = AsyncMock(return_value=return_value)
    return chain


class TestListAuditLogsMongo:
    def test_builds_query_from_filters(self):
        docs = [SimpleNamespace(id="log-1")]
        with patch(
            "src.storage.documents.audit_log.AuditLogDocument.find",
            return_value=_find_chain(docs),
        ) as mock_find:
            result = _run(list_audit_logs_mongo(
                action="login", resource_type="User", user_id="u1",
                status="success", from_date="2026-01-01", to_date="2026-01-31",
            ))

        assert result == docs
        query = mock_find.call_args[0][0]
        assert query["action"] == "LOGIN"
        assert query["resource_type"] == "User"
        assert query["user_id"] == "u1"
        assert query["status"] == "SUCCESS"
        assert query["created_at"]["$gte"] == datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert query["created_at"]["$lte"] == datetime(2026, 1, 31, 23, 59, 59, tzinfo=timezone.utc)

    def test_user_email_filters_both_email_and_actor(self):
        with patch(
            "src.storage.documents.audit_log.AuditLogDocument.find",
            return_value=_find_chain([]),
        ) as mock_find:
            _run(list_audit_logs_mongo(user_email="baya"))

        query = mock_find.call_args[0][0]
        assert len(query["$or"]) == 2
        assert query["$or"][0]["user_email"].search("Baya Chaabene")
        assert query["$or"][1]["actor"].search("baya@biat-it.tn")

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.audit_log.AuditLogDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(list_audit_logs_mongo())
        assert result is None


class TestResourceHistoryMongo:
    def test_matches_resource_id_or_entity_id(self):
        docs = [SimpleNamespace(id="log-1")]
        with patch(
            "src.storage.documents.audit_log.AuditLogDocument.find",
            return_value=_find_chain(docs),
        ) as mock_find:
            result = _run(resource_history_mongo("Invoice", "inv-1"))

        assert result == docs
        query = mock_find.call_args[0][0]
        assert query["resource_type"] == "Invoice"
        assert query["$or"] == [{"resource_id": "inv-1"}, {"entity_id": "inv-1"}]

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.audit_log.AuditLogDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(resource_history_mongo("Invoice", "inv-1"))
        assert result is None


class TestLogAuditEventNative:
    def test_writes_doc_with_valid_row_hash(self):
        entry = SimpleNamespace(
            user_id="u1", user_email="a@biat-it.tn", user_role="Comptable",
            action="LOGIN_SUCCESS", resource_type="User", resource_id="u1",
            before_value=None, after_value=None, ip_address="1.2.3.4",
            user_agent="pytest", status="SUCCESS", detail="",
        )
        coll = MagicMock()
        coll.insert_one = AsyncMock()
        with patch(
            "src.storage.documents.audit_log.AuditLogDocument.get_pymongo_collection",
            return_value=coll,
        ):
            _run(log_audit_event_native(entry))

        coll.insert_one.assert_awaited_once()
        doc = coll.insert_one.call_args[0][0]
        assert doc["action"] == "LOGIN_SUCCESS"
        assert doc["row_hash"] == compute_row_hash_from_doc(doc)

    def test_swallows_errors_and_never_raises(self):
        entry = SimpleNamespace(
            user_id="u1", user_email="a@biat-it.tn", user_role="Comptable",
            action="LOGIN_SUCCESS", resource_type="User", resource_id="u1",
            before_value=None, after_value=None, ip_address=None,
            user_agent=None, status="SUCCESS", detail="",
        )
        with patch(
            "src.storage.documents.audit_log.AuditLogDocument.get_pymongo_collection",
            side_effect=Exception("mongo down"),
        ):
            _run(log_audit_event_native(entry))  # must not raise


class TestCreateAuditLogNative:
    def test_writes_doc_with_valid_row_hash(self):
        user = {"sub": "u1", "email": "a@biat-it.tn", "role": "Admin"}
        coll = MagicMock()
        coll.insert_one = AsyncMock()
        with patch(
            "src.storage.documents.audit_log.AuditLogDocument.get_pymongo_collection",
            return_value=coll,
        ):
            _run(_create_audit_log_native(user, "BUDGET_PLAN_CREATED", "BudgetPlan", "cat-1/2026", "detail text"))

        doc = coll.insert_one.call_args[0][0]
        assert doc["action"] == "BUDGET_PLAN_CREATED"
        assert doc["actor"] == "a@biat-it.tn"
        assert doc["row_hash"] == compute_row_hash_from_doc(doc)

    def test_swallows_errors_and_never_raises(self):
        with patch(
            "src.storage.documents.audit_log.AuditLogDocument.get_pymongo_collection",
            side_effect=Exception("mongo down"),
        ):
            _run(_create_audit_log_native({}, "X", "Y", "z"))  # must not raise


class TestVerifyIntegrityNative:
    def _doc(self, action: str, row_hash) -> dict:
        doc = {
            "_id": "log-1", "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "user_id": "u1", "action": action, "resource_type": "Invoice",
            "resource_id": "inv-1", "status": "SUCCESS", "ip_address": "1.2.3.4",
        }
        doc["row_hash"] = row_hash
        return doc

    def _coll_with_docs(self, docs):
        coll = MagicMock()
        find_result = MagicMock()
        find_result.sort.return_value = find_result
        find_result.limit.return_value = find_result
        find_result.to_list = AsyncMock(return_value=docs)
        coll.find.return_value = find_result
        return coll

    def test_valid_entry_is_counted(self):
        valid_doc = self._doc("LOGIN_SUCCESS", None)
        valid_doc["row_hash"] = compute_row_hash_from_doc(valid_doc)
        coll = self._coll_with_docs([valid_doc])

        with patch(
            "src.storage.documents.audit_log.AuditLogDocument.get_pymongo_collection",
            return_value=coll,
        ):
            result = _run(verify_integrity_native())

        assert result["total_checked"] == 1
        assert result["valid"] == 1
        assert result["tampered_count"] == 0
        assert result["null_hash_count"] == 0

    def test_tampered_entry_is_detected(self):
        tampered_doc = self._doc("AI_EXTRACT", "not-the-real-hash")
        coll = self._coll_with_docs([tampered_doc])

        with patch(
            "src.storage.documents.audit_log.AuditLogDocument.get_pymongo_collection",
            return_value=coll,
        ):
            result = _run(verify_integrity_native())

        assert result["tampered_count"] == 1
        assert result["tampered_entries"][0]["id"] == "log-1"

    def test_rebaselined_entry_is_not_counted_as_tampered(self):
        """Mirrors SQLite's verify_row_status() 'rebaselined' bucket — see
        scripts/rebaseline_audit_hmac_mongo.py and docs/audit_hmac_incident.md
        section 7."""
        doc = self._doc("LOGIN_SUCCESS", "stale-pre-rotation-hash")
        doc["rebaseline_hash"] = compute_row_hash_from_doc(doc)
        doc["rebaselined_at"] = datetime(2026, 9, 7, tzinfo=timezone.utc)
        coll = self._coll_with_docs([doc])

        with patch(
            "src.storage.documents.audit_log.AuditLogDocument.get_pymongo_collection",
            return_value=coll,
        ):
            result = _run(verify_integrity_native())

        assert result["tampered_count"] == 0
        assert result["rebaselined_count"] == 1
        assert result["rebaselined_entries"][0]["id"] == "log-1"

    def test_null_hash_entry_counts_as_valid_but_tracked_separately(self):
        legacy_doc = self._doc("LEGACY_ACTION", None)
        coll = self._coll_with_docs([legacy_doc])

        with patch(
            "src.storage.documents.audit_log.AuditLogDocument.get_pymongo_collection",
            return_value=coll,
        ):
            result = _run(verify_integrity_native())

        assert result["valid"] == 1
        assert result["null_hash_count"] == 1
        assert result["tampered_count"] == 0

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.audit_log.AuditLogDocument.get_pymongo_collection",
            side_effect=Exception("mongo down"),
        ):
            result = _run(verify_integrity_native())
        assert result is None
