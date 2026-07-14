"""Unit tests — sync Mongo helpers backing AuditAgent (Lot 1):
echeancier_kpis_sync, save_audit_snapshot_sync, get_latest_snapshot_sync.

No real MongoDB connection: sync_mongo_repository._get_db() is monkeypatched
with in-memory fakes, matching test_insight_agent_kpis_mongo.py's pattern.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.storage import sync_mongo_repository
from src.storage.sync_mongo_repository import (
    echeancier_kpis_sync, get_latest_snapshot_sync, save_audit_snapshot_sync,
)


class _FakeCollection:
    def __init__(self, docs: list[dict]):
        self._docs = docs
        self.inserted: list[dict] = []

    def count_documents(self, query: dict) -> int:
        return len(self._match(query))

    def find(self, query: dict | None = None, projection: dict | None = None):
        return _FakeCursor(self._match(query or {}))

    def insert_one(self, doc: dict):
        self.inserted.append(doc)
        self._docs.append(doc)

    def _match(self, query: dict) -> list[dict]:
        out = []
        for d in self._docs:
            if all(d.get(k) == v for k, v in query.items()):
                out.append(d)
        return out


class _FakeCursor(list):
    """Minimal stand-in for a pymongo Cursor — supports the .sort().limit() chain."""

    def sort(self, key, direction):
        reverse = direction < 0
        return _FakeCursor(sorted(self, key=lambda d: d[key], reverse=reverse))

    def limit(self, n):
        return _FakeCursor(self[:n])


# ── echeancier_kpis_sync ──────────────────────────────────────────────────────

def test_echeancier_kpis_sync_counts_and_sums_penalties(monkeypatch):
    docs = [
        {"status": "LATE", "base_amount": 100.0, "current_amount": 110.0},
        {"status": "LATE", "base_amount": 200.0, "current_amount": 220.0},
        {"status": "PENDING", "base_amount": 50.0, "current_amount": 50.0},
        {"status": "PAID", "base_amount": 300.0, "current_amount": 300.0},
    ]
    monkeypatch.setattr(
        sync_mongo_repository, "_get_db", lambda: {"payment_installments": _FakeCollection(docs)}
    )

    result = echeancier_kpis_sync()

    assert result["n_total"] == 4
    assert result["n_late"] == 2
    assert result["n_pending"] == 1
    assert result["total_penalty_amount"] == pytest.approx(30.0)


def test_echeancier_kpis_sync_no_late_installments(monkeypatch):
    docs = [{"status": "PENDING", "base_amount": 50.0, "current_amount": 50.0}]
    monkeypatch.setattr(
        sync_mongo_repository, "_get_db", lambda: {"payment_installments": _FakeCollection(docs)}
    )

    result = echeancier_kpis_sync()

    assert result["n_late"] == 0
    assert result["total_penalty_amount"] == 0.0


# ── save_audit_snapshot_sync / get_latest_snapshot_sync ───────────────────────

def test_save_audit_snapshot_sync_writes_expected_shape(monkeypatch):
    coll = _FakeCollection([])
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: {"audit_snapshots": coll})

    period_start = datetime(2026, 7, 14, tzinfo=timezone.utc)
    period_end = datetime(2026, 7, 14, tzinfo=timezone.utc)
    snapshot_id = save_audit_snapshot_sync({
        "granularity": "DAILY",
        "period_start": period_start,
        "period_end": period_end,
        "status": "OK",
        "metrics": {"invoices": {"pending_count": 3}},
        "trend": {},
        "alerts": [],
    })

    assert isinstance(snapshot_id, str) and "-" in snapshot_id  # string UUID with dashes
    assert len(coll.inserted) == 1
    doc = coll.inserted[0]
    assert doc["_id"] == snapshot_id
    assert doc["granularity"] == "DAILY"
    assert doc["metrics"] == {"invoices": {"pending_count": 3}}
    assert doc["reconciliation"] == {}          # Lot 2 field, default
    assert doc["similar_incidents"] == []       # Lot 3 field, default
    assert doc["narrative_summary"] is None     # Lot 3 field, default


def test_get_latest_snapshot_sync_returns_most_recent_same_granularity(monkeypatch):
    older = {
        "_id": "s1", "granularity": "DAILY",
        "period_start": datetime(2026, 7, 12, tzinfo=timezone.utc),
        "metrics": {"invoices": {"pending_count": 1}},
    }
    newer = {
        "_id": "s2", "granularity": "DAILY",
        "period_start": datetime(2026, 7, 13, tzinfo=timezone.utc),
        "metrics": {"invoices": {"pending_count": 5}},
    }
    other_granularity = {
        "_id": "s3", "granularity": "WEEKLY",
        "period_start": datetime(2026, 7, 13, tzinfo=timezone.utc),
        "metrics": {"invoices": {"pending_count": 99}},
    }
    coll = _FakeCollection([older, newer, other_granularity])
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: {"audit_snapshots": coll})

    result = get_latest_snapshot_sync("DAILY")

    assert result["_id"] == "s2"


def test_get_latest_snapshot_sync_returns_none_when_empty(monkeypatch):
    coll = _FakeCollection([])
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: {"audit_snapshots": coll})

    assert get_latest_snapshot_sync("MONTHLY") is None
