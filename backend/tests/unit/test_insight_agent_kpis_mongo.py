"""Unit tests — sync Mongo KPI helpers used by InsightAgent._gather_kpis().

No real MongoDB connection: sync_mongo_repository._get_db() is monkeypatched
with in-memory fakes, matching test_sync_mongo_invoice_status.py's pattern.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src.storage import sync_mongo_repository
from src.storage.sync_mongo_repository import (
    budget_variance_kpis_sync,
    invoice_pending_rejected_30d_sync,
    risks_kpis_sync,
    roadmap_kpis_sync,
)


class _FakeCollection:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    def _matches(self, doc: dict, query: dict) -> bool:
        for key, cond in query.items():
            value = doc.get(key)
            if isinstance(cond, dict):
                if "$in" in cond and value not in cond["$in"]:
                    return False
                if "$nin" in cond and value in cond["$nin"]:
                    return False
                if "$gte" in cond and not (value is not None and value >= cond["$gte"]):
                    return False
                if "$lt" in cond and not (value is not None and value < cond["$lt"]):
                    return False
                if "$lte" in cond and not (value is not None and value <= cond["$lte"]):
                    return False
                if "$ne" in cond and value == cond["$ne"]:
                    return False
            elif value != cond:
                return False
        return True

    def count_documents(self, query: dict) -> int:
        return sum(1 for d in self._docs if self._matches(d, query))

    def find(self, query: dict | None = None):
        query = query or {}
        return [d for d in self._docs if self._matches(d, query)]

    def aggregate(self, pipeline):
        match = pipeline[0]["$match"]
        group_id = pipeline[1]["$group"]["_id"]
        sums: dict[str, float] = {}
        for d in self._docs:
            if not self._matches(d, match):
                continue
            key = d.get(group_id.lstrip("$")) if isinstance(group_id, str) else None
            sums[key] = sums.get(key, 0.0) + (d.get("amount_ht") or 0)
        return [{"_id": k, "total": v} for k, v in sums.items()]


class _FakeDB(dict):
    def __getitem__(self, name):
        return super().setdefault(name, _FakeCollection([]))


def test_invoice_pending_rejected_30d_sync(monkeypatch):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=45)
    docs = [
        {"received_at": now, "status": "RECEIVED"},
        {"received_at": now, "status": "VALIDATING"},
        {"received_at": now, "status": "REJECTED"},
        {"received_at": now, "status": "EXPORTED"},
        {"received_at": old, "status": "REJECTED"},  # outside 30d window
    ]
    db = _FakeDB()
    db["invoices"] = _FakeCollection(docs)
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: db)

    result = invoice_pending_rejected_30d_sync()
    assert result["pending_count"] == 2
    assert result["rejection_rate"] == pytest.approx(25.0)


def test_roadmap_kpis_sync(monkeypatch):
    today = _to_dt(date.today())
    past = _to_dt(date.today() - timedelta(days=10))
    docs = [
        {"date_fin": past, "statut": "EN_COURS"},
        {"date_fin": today, "statut": "TERMINE"},
        {"date_fin": past, "statut": "TERMINE"},
        {"statut": "TERMINE", "date_fin": past},
    ]
    db = _FakeDB()
    db["feuilles_de_route"] = _FakeCollection(docs)
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: db)

    result = roadmap_kpis_sync()
    assert result["n_overdue_milestones"] == 1
    assert result["pct_done"] == pytest.approx(75.0)


def test_risks_kpis_sync(monkeypatch):
    past = _to_dt(date.today() - timedelta(days=5))
    docs = [
        {"niveau_criticite": "CRITIQUE", "statut": "IDENTIFIE", "date_echeance_mitigation": past},
        {"niveau_criticite": "CRITIQUE", "statut": "MAITRISE", "date_echeance_mitigation": past},
        {"niveau_criticite": "FAIBLE", "statut": "IDENTIFIE", "date_echeance_mitigation": past},
    ]
    db = _FakeDB()
    db["risques"] = _FakeCollection(docs)
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: db)

    result = risks_kpis_sync()
    assert result["n_critique"] == 1
    assert result["n_overdue_mitigation"] == 2


def test_budget_variance_kpis_sync(monkeypatch):
    year = date.today().year
    plan_docs = [
        {"catalog_id": "licences_ms365", "year": year, "monthly": [100.0] * 12},
        {"catalog_id": "steg", "year": year, "monthly": [200.0] * 12},
    ]
    invoice_docs = [
        {
            "status": "VALIDATED", "direction": "SUPPLIER",
            "invoice_date": datetime.now(timezone.utc),
            "cost_catalog_id": "licences_ms365", "amount_ht": 5000.0,
        },
        {
            "status": "VALIDATED", "direction": "SUPPLIER",
            "invoice_date": datetime.now(timezone.utc),
            "cost_catalog_id": "steg", "amount_ht": 50.0,
        },
    ]
    db = _FakeDB()
    db["budget_plan_entries"] = _FakeCollection(plan_docs)
    db["invoices"] = _FakeCollection(invoice_docs)
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: db)

    result = budget_variance_kpis_sync()
    assert result["n_total"] == 2
    assert result["n_over_budget"] == 1  # licences_ms365 over, steg under


def _to_dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
