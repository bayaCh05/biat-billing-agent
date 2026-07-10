"""Unit tests — service_bridge.py invoices/billing/payments functions
(Tier 1, sub-batch 3 — the last of the scoped test-coverage plan's Tier 1:
auth writes, audit, invoices/payments).

Covers list_invoices_mongo, get_invoice_mongo, get_journal_entry_for_invoice_
mongo, list_client_invoices_mongo, get_installments_summary_mongo,
list_installments_mongo, update_invoice_status_native, and mark_installment_
paid_native. mirror_invoice/mirror_client_invoice/mirror_installment_paid
were in this domain too but are confirmed dead code (removed separately —
see the dead-code-removal commit), so there's nothing to test there.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.storage.documents.service_bridge import (
    _NOT_FOUND,
    get_installments_summary_mongo,
    get_invoice_mongo,
    get_journal_entry_for_invoice_mongo,
    list_client_invoices_mongo,
    list_installments_mongo,
    list_invoices_mongo,
    mark_installment_paid_native,
    update_invoice_status_native,
)


def _run(coro):
    return asyncio.run(coro)


def _find_chain(return_value):
    chain = MagicMock()
    chain.sort.return_value = chain
    chain.limit.return_value = chain
    chain.to_list = AsyncMock(return_value=return_value)
    return chain


class TestListInvoicesMongo:
    def test_converts_each_doc_and_returns_list(self):
        docs = [SimpleNamespace(id="inv-1"), SimpleNamespace(id="inv-2")]
        with (
            patch(
                "src.storage.documents.invoice.InvoiceDocument.find",
                return_value=_find_chain(docs),
            ),
            patch(
                "src.storage.documents.service_bridge._invoice_doc_to_record",
                side_effect=lambda d: f"record-{d.id}",
            ),
        ):
            result = _run(list_invoices_mongo(100))
        assert result == ["record-inv-1", "record-inv-2"]

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.invoice.InvoiceDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(list_invoices_mongo(100))
        assert result is None


class TestGetInvoiceMongo:
    def test_returns_converted_record_when_found(self):
        doc = SimpleNamespace(id="inv-1")
        with (
            patch(
                "src.storage.documents.invoice.InvoiceDocument.find_one",
                new=AsyncMock(return_value=doc),
            ) as mock_find,
            patch(
                "src.storage.documents.service_bridge._invoice_doc_to_record",
                return_value="record-inv-1",
            ),
        ):
            result = _run(get_invoice_mongo("inv-1"))
        assert result == "record-inv-1"
        mock_find.assert_awaited_once_with({"_id": "inv-1"})

    def test_returns_not_found_sentinel_when_absent(self):
        with patch(
            "src.storage.documents.invoice.InvoiceDocument.find_one",
            new=AsyncMock(return_value=None),
        ):
            result = _run(get_invoice_mongo("inv-missing"))
        assert result is _NOT_FOUND

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.invoice.InvoiceDocument.find_one",
            side_effect=Exception("mongo down"),
        ):
            result = _run(get_invoice_mongo("inv-1"))
        assert result is None


class TestGetJournalEntryForInvoiceMongo:
    def test_returns_empty_dict_when_no_entry(self):
        with patch(
            "src.storage.documents.journal_entry.JournalEntryDocument.find_one",
            new=AsyncMock(return_value=None),
        ):
            result = _run(get_journal_entry_for_invoice_mongo("inv-1"))
        assert result == {}

    def test_returns_balanced_entry_shape(self):
        entry = SimpleNamespace(
            id="entry-1", reference="JNL-2026-0001", date_ecriture=date(2026, 1, 1),
            description="Facture Ooredoo", accounting_explanation="...",
            lines=[
                SimpleNamespace(compte="401", libelle="Fournisseur", debit=0, credit=100),
                SimpleNamespace(compte="6xxx", libelle="Charge", debit=100, credit=0),
            ],
        )
        with patch(
            "src.storage.documents.journal_entry.JournalEntryDocument.find_one",
            new=AsyncMock(return_value=entry),
        ):
            result = _run(get_journal_entry_for_invoice_mongo("inv-1"))

        assert result["is_balanced"] is True
        assert result["id"] == "entry1"  # dashes stripped
        assert len(result["lines"]) == 2

    def test_detects_unbalanced_entry(self):
        entry = SimpleNamespace(
            id="entry-1", reference="JNL-2026-0001", date_ecriture=date(2026, 1, 1),
            description="", accounting_explanation=None,
            lines=[SimpleNamespace(compte="401", libelle="", debit=0, credit=99)],
        )
        with patch(
            "src.storage.documents.journal_entry.JournalEntryDocument.find_one",
            new=AsyncMock(return_value=entry),
        ):
            result = _run(get_journal_entry_for_invoice_mongo("inv-1"))
        assert result["is_balanced"] is False
        assert "DÉSÉQUILIBRÉE" in result["summary"]

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.journal_entry.JournalEntryDocument.find_one",
            side_effect=Exception("mongo down"),
        ):
            result = _run(get_journal_entry_for_invoice_mongo("inv-1"))
        assert result is None


class TestListClientInvoicesMongo:
    def test_converts_each_doc(self):
        docs = [SimpleNamespace(id="ci-1")]
        with (
            patch(
                "src.storage.documents.client_invoice.ClientInvoiceDocument.find",
                return_value=_find_chain(docs),
            ),
            patch(
                "src.storage.documents.service_bridge._client_invoice_doc_to_pydantic",
                return_value="pydantic-ci-1",
            ),
        ):
            result = _run(list_client_invoices_mongo())
        assert result == ["pydantic-ci-1"]

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.client_invoice.ClientInvoiceDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(list_client_invoices_mongo())
        assert result is None


class TestGetInstallmentsSummaryMongo:
    def test_aggregates_by_status_and_penalties(self):
        docs = [
            SimpleNamespace(status="LATE", base_amount=100.0, current_amount=110.0, due_date=None),
            SimpleNamespace(status="PENDING", base_amount=50.0, current_amount=50.0,
                             due_date=date(2026, 12, 31)),
            SimpleNamespace(status="PAID", base_amount=200.0, current_amount=200.0, due_date=None),
        ]
        with patch(
            "src.storage.documents.payment_installment.PaymentInstallmentDocument.find",
            return_value=_find_chain(docs),
        ):
            result = _run(get_installments_summary_mongo())

        assert result["total"] == 3
        assert result["late_count"] == 1
        assert result["pending_count"] == 1
        assert result["paid_count"] == 1
        assert result["total_penalties"] == 10.0
        assert result["next_due_date"] == "2026-12-31"

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.payment_installment.PaymentInstallmentDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(get_installments_summary_mongo())
        assert result is None


class TestListInstallmentsMongo:
    def test_joins_invoice_metadata_and_filters_by_status(self):
        installment = SimpleNamespace(
            id="inst-1", invoice_id="inv-1", status="LATE",
            installment_number=1, total_installments=3,
            base_amount=100.0, current_amount=110.0,
            due_date=date(2020, 1, 1), paid_date=None, paid_amount=None, late_periods=2,
        )
        invoice = SimpleNamespace(id="inv-1", issuer_name="Ooredoo", invoice_number="FAC-1")
        with (
            patch(
                "src.storage.documents.payment_installment.PaymentInstallmentDocument.find",
                return_value=_find_chain([installment]),
            ),
            patch(
                "src.storage.documents.invoice.InvoiceDocument.find",
                return_value=_find_chain([invoice]),
            ),
        ):
            result = _run(list_installments_mongo(["LATE"]))

        assert len(result) == 1
        row = result[0]
        assert row["issuer_name"] == "Ooredoo"
        assert row["invoice_number"] == "FAC-1"
        assert row["penalty_amount"] == 10.0
        assert row["days_overdue"] > 0

    def test_filters_out_statuses_not_requested(self):
        installment = SimpleNamespace(
            id="inst-1", invoice_id="inv-1", status="PAID",
            installment_number=1, total_installments=1,
            base_amount=100.0, current_amount=100.0,
            due_date=date(2026, 1, 1), paid_date=date(2026, 1, 1), paid_amount=100.0, late_periods=0,
        )
        with (
            patch(
                "src.storage.documents.payment_installment.PaymentInstallmentDocument.find",
                return_value=_find_chain([installment]),
            ),
            patch(
                "src.storage.documents.invoice.InvoiceDocument.find",
                return_value=_find_chain([]),
            ),
        ):
            result = _run(list_installments_mongo(["LATE", "PENDING"]))
        assert result == []

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.payment_installment.PaymentInstallmentDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(list_installments_mongo([]))
        assert result is None


class TestUpdateInvoiceStatusNative:
    def test_returns_none_when_invoice_not_found(self):
        with patch(
            "src.storage.documents.service_bridge._get_by_str_id",
            new=AsyncMock(return_value=None),
        ):
            result = _run(update_invoice_status_native(
                "12345678-1234-1234-1234-123456789012", "VALIDATED",
            ))
        assert result is None

    def test_updates_status_and_pushes_history(self):
        existing = SimpleNamespace(id="inv-1", status="RECEIVED")
        updated = SimpleNamespace(id="inv-1", status="VALIDATED")
        coll = MagicMock()
        coll.update_one = AsyncMock()
        with (
            patch(
                "src.storage.documents.service_bridge._get_by_str_id",
                new=AsyncMock(side_effect=[existing, updated]),
            ),
            patch(
                "src.storage.documents.invoice.InvoiceDocument.get_pymongo_collection",
                return_value=coll,
            ),
        ):
            result = _run(update_invoice_status_native(
                "12345678-1234-1234-1234-123456789012", "VALIDATED",
            ))

        assert result is updated
        update = coll.update_one.call_args[0][1]
        assert update["$set"]["status"] == "VALIDATED"
        assert update["$push"]["history"]["from_status"] == "RECEIVED"
        assert update["$push"]["history"]["to_status"] == "VALIDATED"


class TestMarkInstallmentPaidNative:
    def test_returns_none_when_not_found(self):
        with patch(
            "src.storage.documents.payment_installment.PaymentInstallmentDocument.find_one",
            new=AsyncMock(return_value=None),
        ):
            result = _run(mark_installment_paid_native("inst-1", 100.0, "2026-01-01"))
        assert result is None

    def test_returns_already_paid_marker_when_already_paid(self):
        doc = SimpleNamespace(id="inst-1", status="PAID")
        with patch(
            "src.storage.documents.payment_installment.PaymentInstallmentDocument.find_one",
            new=AsyncMock(return_value=doc),
        ):
            result = _run(mark_installment_paid_native("inst-1", 100.0, "2026-01-01"))
        assert result == "ALREADY_PAID"

    def test_marks_paid_and_returns_updated_doc(self):
        pending = SimpleNamespace(id="inst-1", status="PENDING")
        updated = SimpleNamespace(id="inst-1", status="PAID")
        coll = MagicMock()
        coll.update_one = AsyncMock()
        with (
            patch(
                "src.storage.documents.payment_installment.PaymentInstallmentDocument.find_one",
                new=AsyncMock(side_effect=[pending, updated]),
            ),
            patch(
                "src.storage.documents.payment_installment.PaymentInstallmentDocument.get_pymongo_collection",
                return_value=coll,
            ),
        ):
            result = _run(mark_installment_paid_native("inst-1", 250.5, "2026-03-15"))

        assert result is updated
        update = coll.update_one.call_args[0][1]["$set"]
        assert update["status"] == "PAID"
        assert update["paid_amount"] == 250.5
        assert update["paid_date"] == datetime(2026, 3, 15, tzinfo=timezone.utc)
