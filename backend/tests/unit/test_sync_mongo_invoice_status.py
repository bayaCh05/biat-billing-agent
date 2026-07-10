"""Unit tests — SyncMongoInvoiceRepository.get_by_status/count_by_status.

Added so the ML retrain job/endpoint (scheduler.py::_job_retrain_classifier,
ai.py::retrain_model) can read invoice data from Mongo instead of the
SQLAlchemy repository, which only ever sees a frozen migration-time
snapshot — invoices uploaded through the real API (AIOrchestrator) land
in Mongo only. No real MongoDB connection: _get_db() is monkeypatched
with an in-memory fake, matching the rest of this module's test suite
(see test_ai_audit_sync.py).
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from src.models.enums import InvoiceStatus
from src.storage import sync_mongo_repository
from src.storage.sync_mongo_repository import SyncMongoInvoiceRepository


def _doc(status: str, cost_catalog_id: str | None = "licences_ms365") -> dict:
    return {
        "_id": str(uuid4()),
        "file_hash": f"hash-{uuid4()}",
        "raw_file_path": "/tmp/x.pdf",
        "direction": "SUPPLIER",
        "status": status,
        "cost_catalog_id": cost_catalog_id,
    }


class _FakeCollection:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    def find(self, query: dict):
        status = query.get("status")
        return [d for d in self._docs if d.get("status") == status]

    def aggregate(self, pipeline):
        counts: dict[str, int] = {}
        for d in self._docs:
            counts[d["status"]] = counts.get(d["status"], 0) + 1
        return [{"_id": k, "count": v} for k, v in counts.items()]


@pytest.fixture
def repo(monkeypatch):
    docs = [
        _doc("VALIDATED"), _doc("VALIDATED"),
        _doc("EXPORTED"),
        _doc("JOURNALED"),
        _doc("FLAGGED"),
    ]
    coll = _FakeCollection(docs)
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: {"invoices": coll})
    return SyncMongoInvoiceRepository()


class TestGetByStatus:
    def test_returns_only_matching_status(self, repo):
        result = repo.get_by_status(InvoiceStatus.VALIDATED)
        assert len(result) == 2
        assert all(inv.status == InvoiceStatus.VALIDATED for inv in result)

    def test_returns_empty_list_when_no_match(self, repo):
        assert repo.get_by_status(InvoiceStatus.REJECTED) == []

    def test_result_items_are_invoice_records_with_cost_catalog_id(self, repo):
        result = repo.get_by_status(InvoiceStatus.EXPORTED)
        assert len(result) == 1
        assert result[0].cost_catalog_id == "licences_ms365"


class TestCountByStatus:
    def test_counts_all_statuses(self, repo):
        counts = repo.count_by_status()
        assert counts == {"VALIDATED": 2, "EXPORTED": 1, "JOURNALED": 1, "FLAGGED": 1}

    def test_sums_used_by_retrain_threshold(self, repo):
        counts = repo.count_by_status()
        n_labelled = (
            counts.get(InvoiceStatus.VALIDATED.value, 0)
            + counts.get(InvoiceStatus.EXPORTED.value, 0)
            + counts.get(InvoiceStatus.PAID.value, 0)
            + counts.get(InvoiceStatus.JOURNALED.value, 0)
        )
        assert n_labelled == 4  # 2 VALIDATED + 1 EXPORTED + 0 PAID + 1 JOURNALED
