"""Regression tests — PATCH /ai/invoices/{id}/classification must read/write
via MongoDB, not the SQLAlchemy classification_feedback table.

Before this fix (Lot A8), this endpoint read the invoice via the SQLAlchemy
InvoiceRepository — which never sees invoices uploaded through the real API
(InvoiceProcessingOrchestrator writes Mongo-only) — and wrote feedback to a SQLite-only
table with no Mongo equivalent at all. ClassificationFeedbackDocument already
existed as an unused Beanie schema; these tests prove it's now actually
written to, and that the invoice read/write and retrain trigger go through
SyncMongoInvoiceRepository, matching test_ml_retrain_wiring.py's pattern.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.storage import sync_mongo_repository
from src.storage.sync_mongo_repository import (
    count_classification_feedback_sync,
    save_classification_feedback_sync,
)


class _FakeCollection:
    def __init__(self):
        self.docs: list[dict] = []

    def insert_one(self, doc: dict):
        self.docs.append(doc)

    def count_documents(self, query: dict):
        return len(self.docs)


class _FakeDB(dict):
    def __getitem__(self, name):
        return super().setdefault(name, _FakeCollection())


@pytest.fixture
def db(monkeypatch):
    fake = _FakeDB()
    monkeypatch.setattr(sync_mongo_repository, "_get_db", lambda: fake)
    return fake


class TestSaveClassificationFeedbackSync:
    def test_inserts_feedback_document(self, db):
        save_classification_feedback_sync(
            invoice_id="inv-1", original_compte="606", corrected_compte="6112",
            original_catalog_id="fournitures_bureau", corrected_catalog_id="maintenance_informatique",
            invoice_text="texte facture", corrected_by="comptable@biat-it.tn",
        )
        docs = db["classification_feedback"].docs
        assert len(docs) == 1
        assert docs[0]["invoice_id"] == "inv-1"
        assert docs[0]["corrected_compte"] == "6112"
        assert isinstance(docs[0]["corrected_at"], datetime)

    def test_count_reflects_inserted_feedback(self, db):
        assert count_classification_feedback_sync() == 0
        for i in range(3):
            save_classification_feedback_sync(
                invoice_id=f"inv-{i}", original_compte="606", corrected_compte="6112",
                original_catalog_id=None, corrected_catalog_id=None,
                invoice_text="", corrected_by="admin@biat-it.tn",
            )
        assert count_classification_feedback_sync() == 3


class TestCorrectClassificationEndpoint:
    def _fake_invoice(self):
        return SimpleNamespace(
            accounting_compte="606", cost_catalog_id="fournitures_bureau",
            raw_extracted_text="", accounting_label=None,
        )

    def test_reads_and_saves_invoice_via_mongo_repo(self, monkeypatch):
        fake_repo = MagicMock()
        fake_repo.get_by_id.return_value = self._fake_invoice()
        monkeypatch.setattr(
            "src.storage.sync_mongo_repository.SyncMongoInvoiceRepository",
            lambda: fake_repo,
        )
        monkeypatch.setattr(
            "src.storage.sync_mongo_repository.save_classification_feedback_sync",
            lambda **kw: None,
        )
        monkeypatch.setattr(
            "src.storage.sync_mongo_repository.count_classification_feedback_sync",
            lambda: 1,
        )

        from api.routers.ai import correct_classification

        body = SimpleNamespace(
            accounting_compte="6112", cost_catalog_id="maintenance_informatique",
            invoice_text="",
        )
        user = SimpleNamespace(email="comptable@biat-it.tn")

        result = correct_classification(str(_FIXED_UUID), body, user)

        assert result["invoice_id"] == str(_FIXED_UUID)
        assert result["corrected_compte"] == "6112"
        assert result["feedback_count"] == 1
        fake_repo.get_by_id.assert_called_once()
        fake_repo.save.assert_called_once()

    def test_invalid_uuid_raises_400(self, monkeypatch):
        from fastapi import HTTPException

        from api.routers.ai import correct_classification

        body = SimpleNamespace(accounting_compte="6112", cost_catalog_id="x", invoice_text="")
        user = SimpleNamespace(email="comptable@biat-it.tn")

        with pytest.raises(HTTPException) as exc_info:
            correct_classification("not-a-uuid", body, user)
        assert exc_info.value.status_code == 400

    def test_missing_invoice_raises_404(self, monkeypatch):
        from fastapi import HTTPException

        fake_repo = MagicMock()
        fake_repo.get_by_id.return_value = None
        monkeypatch.setattr(
            "src.storage.sync_mongo_repository.SyncMongoInvoiceRepository",
            lambda: fake_repo,
        )

        from api.routers.ai import correct_classification

        body = SimpleNamespace(accounting_compte="6112", cost_catalog_id="x", invoice_text="")
        user = SimpleNamespace(email="comptable@biat-it.tn")

        with pytest.raises(HTTPException) as exc_info:
            correct_classification(str(_FIXED_UUID), body, user)
        assert exc_info.value.status_code == 404

    def test_retrain_triggered_at_threshold(self, monkeypatch):
        fake_repo = MagicMock()
        fake_repo.get_by_id.return_value = self._fake_invoice()
        monkeypatch.setattr(
            "src.storage.sync_mongo_repository.SyncMongoInvoiceRepository",
            lambda: fake_repo,
        )
        monkeypatch.setattr(
            "src.storage.sync_mongo_repository.save_classification_feedback_sync",
            lambda **kw: None,
        )
        monkeypatch.setattr(
            "src.storage.sync_mongo_repository.count_classification_feedback_sync",
            lambda: 10,
        )
        fake_components = MagicMock()
        monkeypatch.setattr("api.routers.ai.get_components", lambda: fake_components)

        from api.routers.ai import correct_classification

        body = SimpleNamespace(accounting_compte="6112", cost_catalog_id="x", invoice_text="")
        user = SimpleNamespace(email="admin@biat-it.tn")

        result = correct_classification(str(_FIXED_UUID), body, user)

        assert result["retrain_triggered"] is True
        fake_components.coder.ml_classifier.retrain_from_repo.assert_called_once_with(fake_repo)
        fake_components.close.assert_called_once()


_FIXED_UUID = "12345678-1234-1234-1234-123456789012"
