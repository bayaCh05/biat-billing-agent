"""Unit tests — rapprochement transversal déterministe (Audit Agent, Lot 2) :
invoices_overdue_without_installment_plan_sync, late_installments_invoice_not_flagged_sync,
budget_overrun_top_invoices_sync, invoices_journal_mismatch_sync.

No real MongoDB connection: sync_mongo_repository._get_db() is monkeypatched
with in-memory fakes, matching test_insight_agent_kpis_mongo.py's pattern.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src.storage import sync_mongo_repository
from src.storage.sync_mongo_repository import (
    budget_overrun_top_invoices_sync, invoices_journal_mismatch_sync,
    invoices_overdue_without_installment_plan_sync,
    late_installments_invoice_not_flagged_sync,
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
                if "$lt" in cond and not (value is not None and value < cond["$lt"]):
                    return False
                if "$gte" in cond and not (value is not None and value >= cond["$gte"]):
                    return False
                if "$lte" in cond and not (value is not None and value <= cond["$lte"]):
                    return False
                if "$ne" in cond and value == cond["$ne"]:
                    return False
            elif value != cond:
                return False
        return True

    def count_documents(self, query: dict) -> int:
        return len(self.find(query))

    def find(self, query: dict | None = None, projection: dict | None = None):
        query = query or {}
        return [d for d in self._docs if self._matches(d, query)]


class _FakeDB(dict):
    def __getitem__(self, name):
        return super().setdefault(name, _FakeCollection([]))


def _to_dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


# ── invoices_overdue_without_installment_plan_sync ────────────────────────────

def test_overdue_invoice_without_any_installment_is_flagged(monkeypatch):
    past = _to_dt(date.today() - timedelta(days=10))
    db = _FakeDB()
    db["invoices"] = _FakeCollection([
        {"_id": "inv-1", "due_date": past, "status": "VALIDATED", "invoice_number": "F001"},
    ])
    db["payment_installments"] = _FakeCollection([])
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: db)

    result = invoices_overdue_without_installment_plan_sync()

    assert result["count"] == 1
    assert result["detail"][0]["invoice_id"] == "inv-1"


def test_overdue_invoice_with_installment_is_not_flagged(monkeypatch):
    past = _to_dt(date.today() - timedelta(days=10))
    db = _FakeDB()
    db["invoices"] = _FakeCollection([
        {"_id": "inv-2", "due_date": past, "status": "VALIDATED", "invoice_number": "F002"},
    ])
    db["payment_installments"] = _FakeCollection([{"invoice_id": "inv-2"}])
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: db)

    result = invoices_overdue_without_installment_plan_sync()

    assert result["count"] == 0


def test_paid_invoice_never_flagged_even_if_overdue(monkeypatch):
    past = _to_dt(date.today() - timedelta(days=10))
    db = _FakeDB()
    db["invoices"] = _FakeCollection([
        {"_id": "inv-3", "due_date": past, "status": "PAID", "invoice_number": "F003"},
    ])
    db["payment_installments"] = _FakeCollection([])
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: db)

    result = invoices_overdue_without_installment_plan_sync()

    assert result["count"] == 0


def test_no_overdue_invoices_returns_empty(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: db)

    result = invoices_overdue_without_installment_plan_sync()

    assert result == {"count": 0, "detail": []}


# ── late_installments_invoice_not_flagged_sync ────────────────────────────────

def test_late_installment_whose_invoice_is_not_flagged_is_reported(monkeypatch):
    db = _FakeDB()
    db["payment_installments"] = _FakeCollection([{"invoice_id": "inv-4", "status": "LATE"}])
    db["invoices"] = _FakeCollection([{"_id": "inv-4", "human_review_required": False}])
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: db)

    result = late_installments_invoice_not_flagged_sync()

    assert result["count"] == 1
    assert result["detail"][0]["invoice_id"] == "inv-4"


def test_late_installment_whose_invoice_is_flagged_is_not_reported(monkeypatch):
    db = _FakeDB()
    db["payment_installments"] = _FakeCollection([{"invoice_id": "inv-5", "status": "LATE"}])
    db["invoices"] = _FakeCollection([{"_id": "inv-5", "human_review_required": True}])
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: db)

    result = late_installments_invoice_not_flagged_sync()

    assert result["count"] == 0


def test_no_late_installments_returns_empty(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: db)

    assert late_installments_invoice_not_flagged_sync() == {"count": 0, "detail": []}


# ── budget_overrun_top_invoices_sync ──────────────────────────────────────────

def test_budget_overrun_lists_top_invoices_for_line_over_budget(monkeypatch):
    year = date.today().year
    db = _FakeDB()
    db["budget_plan_entries"] = _FakeCollection([
        {"catalog_id": "licences_ms365", "year": year, "monthly": [100.0] * 12},
    ])
    now = datetime.now(timezone.utc)
    db["invoices"] = _FakeCollection([
        {
            "_id": "inv-6", "invoice_number": "F010", "status": "VALIDATED", "direction": "SUPPLIER",
            "invoice_date": now, "cost_catalog_id": "licences_ms365", "amount_ht": 800.0,
        },
        {
            "_id": "inv-7", "invoice_number": "F011", "status": "VALIDATED", "direction": "SUPPLIER",
            "invoice_date": now, "cost_catalog_id": "licences_ms365", "amount_ht": 700.0,
        },
    ])
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: db)

    result = budget_overrun_top_invoices_sync(top_n=1)

    assert len(result) == 1
    assert result[0]["catalog_id"] == "licences_ms365"
    assert result[0]["actual_ytd"] == pytest.approx(1500.0)
    assert len(result[0]["top_invoices"]) == 1
    assert result[0]["top_invoices"][0]["invoice_id"] == "inv-6"  # highest amount_ht first


def test_budget_line_under_budget_is_not_listed(monkeypatch):
    year = date.today().year
    db = _FakeDB()
    db["budget_plan_entries"] = _FakeCollection([
        {"catalog_id": "steg", "year": year, "monthly": [1000.0] * 12},
    ])
    db["invoices"] = _FakeCollection([
        {
            "_id": "inv-8", "invoice_number": "F020", "status": "VALIDATED", "direction": "SUPPLIER",
            "invoice_date": datetime.now(timezone.utc), "cost_catalog_id": "steg", "amount_ht": 50.0,
        },
    ])
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: db)

    result = budget_overrun_top_invoices_sync()

    assert result == []


def test_no_budget_plan_entries_returns_empty(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: db)

    assert budget_overrun_top_invoices_sync() == []


# ── invoices_journal_mismatch_sync ────────────────────────────────────────────

def test_journaled_invoice_without_entry_is_missing(monkeypatch):
    db = _FakeDB()
    db["invoices"] = _FakeCollection([{"_id": "inv-9", "status": "JOURNALED", "amount_ttc": 100.0}])
    db["journal_entries"] = _FakeCollection([])
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: db)

    result = invoices_journal_mismatch_sync()

    assert result["missing_entry_count"] == 1
    assert result["missing_entry"][0]["invoice_id"] == "inv-9"
    assert result["duplicate_entry_count"] == 0
    assert result["amount_mismatch_count"] == 0


def test_journaled_invoice_with_two_entries_is_duplicate(monkeypatch):
    db = _FakeDB()
    db["invoices"] = _FakeCollection([{"_id": "inv-10", "status": "JOURNALED", "amount_ttc": 100.0}])
    db["journal_entries"] = _FakeCollection([
        {"source_invoice_id": "inv-10", "reference": "JE-1", "lines": [{"compte": "401", "credit": 100.0}]},
        {"source_invoice_id": "inv-10", "reference": "JE-2", "lines": [{"compte": "401", "credit": 100.0}]},
    ])
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: db)

    result = invoices_journal_mismatch_sync()

    assert result["duplicate_entry_count"] == 1
    assert result["duplicate_entry"][0]["count"] == 2
    assert result["missing_entry_count"] == 0


def test_journaled_invoice_with_amount_mismatch_is_reported(monkeypatch):
    db = _FakeDB()
    db["invoices"] = _FakeCollection([{"_id": "inv-11", "status": "JOURNALED", "amount_ttc": 100.0}])
    db["journal_entries"] = _FakeCollection([
        {"source_invoice_id": "inv-11", "reference": "JE-3", "lines": [{"compte": "401", "credit": 90.0}]},
    ])
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: db)

    result = invoices_journal_mismatch_sync()

    assert result["amount_mismatch_count"] == 1
    assert result["amount_mismatch"][0]["invoice_id"] == "inv-11"
    assert result["amount_mismatch"][0]["journal_amount"] == pytest.approx(90.0)


def test_journaled_invoice_with_matching_entry_is_clean(monkeypatch):
    db = _FakeDB()
    db["invoices"] = _FakeCollection([{"_id": "inv-12", "status": "JOURNALED", "amount_ttc": 100.0}])
    db["journal_entries"] = _FakeCollection([
        {"source_invoice_id": "inv-12", "reference": "JE-4", "lines": [{"compte": "401", "credit": 100.0}]},
    ])
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: db)

    result = invoices_journal_mismatch_sync()

    assert result["missing_entry_count"] == 0
    assert result["duplicate_entry_count"] == 0
    assert result["amount_mismatch_count"] == 0


def test_no_journaled_invoices_returns_all_clean(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: db)

    result = invoices_journal_mismatch_sync()

    assert result["missing_entry_count"] == 0
    assert result["duplicate_entry_count"] == 0
    assert result["amount_mismatch_count"] == 0
