"""Tests unitaires — log_ai_audit_event_sync (équivalent synchrone pour
AIOrchestrator._audit_ai(), testé en isolation AVANT tout branchement au
pipeline réel — voir src/storage/sync_mongo_repository.py).

Aucune connexion MongoDB réelle : _get_db() est monkeypatché avec une
collection en mémoire, comme le reste de la suite unitaire mocke la
persistance (voir CLAUDE.md — "Test Conventions").
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-for-audit-hmac")

from api.security.audit_integrity import verify_row_hash_from_doc
from src.models.audit import AuditLogCreate
from src.storage import sync_mongo_repository


class _FakeCollection:
    def __init__(self):
        self.inserted: list[dict] = []

    def insert_one(self, doc: dict):
        self.inserted.append(doc)


@pytest.fixture
def fake_coll(monkeypatch):
    coll = _FakeCollection()
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: {"audit_logs": coll})
    return coll


def test_log_ai_audit_event_sync_writes_expected_shape(fake_coll):
    entry = AuditLogCreate(
        user_id="system:ai",
        user_email="system:ai",
        user_role="AI",
        action="AI_EXTRACT",
        resource_type="InvoiceRecord",
        resource_id="inv-123",
        status="SUCCESS",
        detail="method=native conf=0.95 review=False",
    )

    sync_mongo_repository.log_ai_audit_event_sync(entry)

    assert len(fake_coll.inserted) == 1
    doc = fake_coll.inserted[0]

    assert doc["action"] == "AI_EXTRACT"
    assert doc["resource_type"] == "InvoiceRecord"
    assert doc["resource_id"] == "inv-123"
    assert doc["entity_id"] == "inv-123"  # backwards-compat alias, same as log_action()
    assert doc["user_role"] == "AI"
    assert doc["status"] == "SUCCESS"
    assert isinstance(doc["_id"], str) and "-" in doc["_id"]  # string UUID with dashes, never native BSON UUID
    assert doc["row_hash"]  # must not be None — this is the whole point of the conversion


def test_log_ai_audit_event_sync_row_hash_is_verifiable(fake_coll):
    entry = AuditLogCreate(
        action="AI_CLASSIFY", resource_type="InvoiceRecord", resource_id="inv-456",
        user_id="system:ai", user_role="AI", detail="catalog=telecom compte=626",
    )
    sync_mongo_repository.log_ai_audit_event_sync(entry)
    doc = fake_coll.inserted[0]

    assert verify_row_hash_from_doc(doc) is True

    tampered = dict(doc)
    tampered["action"] = "AI_JOURNAL"
    assert verify_row_hash_from_doc(tampered) is False


def test_log_ai_audit_event_sync_never_awaited_no_event_loop_needed(fake_coll):
    """Sanity check that this is genuinely synchronous — required since it will
    be called from AIOrchestrator/_audit_ai(), which must never await anything
    (see CLAUDE.md: sync vs async is forced by the caller)."""
    import inspect
    assert not inspect.iscoroutinefunction(sync_mongo_repository.log_ai_audit_event_sync)

    entry = AuditLogCreate(action="AI_ANOMALY", resource_type="InvoiceRecord", resource_id="inv-789")
    result = sync_mongo_repository.log_ai_audit_event_sync(entry)
    assert result is None
    assert len(fake_coll.inserted) == 1


def test_log_ai_audit_event_sync_propagates_mongo_errors(monkeypatch):
    """AIOrchestrator._audit_ai() is responsible for swallowing failures (as it
    already does for the SQLite path) — the writer itself must NOT swallow them,
    otherwise a silent Mongo outage would look identical to a successful audit write."""
    class _BrokenCollection:
        def insert_one(self, doc):
            raise ConnectionError("mongo unreachable")

    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: {"audit_logs": _BrokenCollection()})

    entry = AuditLogCreate(action="AI_JOURNAL", resource_type="InvoiceRecord", resource_id="inv-000")
    with pytest.raises(ConnectionError):
        sync_mongo_repository.log_ai_audit_event_sync(entry)
