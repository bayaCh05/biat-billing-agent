"""Unit tests — service_bridge.py Tier 3, batch A: KPI/analytics/suivi
read-only *_mongo functions.

These are heavier than most of this file (several sequential aggregation
pipelines per function) — mocked at the coll.aggregate(...).to_list()
boundary with one side_effect entry per call, in call order, treating the
exact pipeline stages as an implementation detail and asserting on the
computed/rounded output shape instead.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.storage.documents.service_bridge import (
    analytics_kpis_mongo,
    by_account_mongo,
    by_supplier_mongo,
    get_kpi_mongo,
    get_suivi_invoices_mongo,
    list_journal_entries_mongo,
    monthly_spend_mongo,
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


def _agg_coll(*results):
    """A collection mock whose .aggregate(...).to_list(...) returns each of
    `results` in turn, one per call, matching call order in the source."""
    coll = MagicMock()
    calls = iter(results)

    def _aggregate(pipeline):
        agg_result = MagicMock()
        agg_result.to_list = AsyncMock(return_value=next(calls))
        return agg_result

    coll.aggregate.side_effect = _aggregate
    return coll


class TestListJournalEntriesMongo:
    def test_no_date_range_uses_limit_and_desc_sort(self):
        docs = [SimpleNamespace(id="e1")]
        with patch(
            "src.storage.documents.journal_entry.JournalEntryDocument.find",
            return_value=_find_chain(docs),
        ) as mock_find:
            result = _run(list_journal_entries_mongo(limit=50))
        assert result == docs
        mock_find.assert_called_once_with()

    def test_date_range_filters_and_sorts_ascending(self):
        docs = [SimpleNamespace(id="e1")]
        with patch(
            "src.storage.documents.journal_entry.JournalEntryDocument.find",
            return_value=_find_chain(docs),
        ) as mock_find:
            result = _run(list_journal_entries_mongo(date(2026, 1, 1), date(2026, 1, 31)))
        assert result == docs
        query = mock_find.call_args[0][0]
        assert query["date_ecriture"]["$gte"] == datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert query["date_ecriture"]["$lte"] == datetime(2026, 1, 31, tzinfo=timezone.utc)

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.journal_entry.JournalEntryDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(list_journal_entries_mongo())
        assert result is None


class TestGetKpiMongo:
    def test_computes_shape_from_aggregations(self):
        main = [{"total": 10, "total_ttc": 1000.0, "flagged": 2, "pending": 1, "exposed_ttc": 200.0}]
        by_status = [{"_id": "FLAGGED", "cnt": 2}, {"_id": "EXPORTED", "cnt": 8}]
        auto = [{"total_processed": 8, "auto_approved": 6}]
        blocked = [{"blocked": 50.0}]
        coll = _agg_coll(main, by_status, auto, blocked)

        with patch(
            "src.storage.documents.invoice.InvoiceDocument.get_pymongo_collection",
            return_value=coll,
        ):
            result = _run(get_kpi_mongo())

        assert result["total_invoices"] == 10
        assert result["total_amount_ttc"] == 1000.0
        assert result["auto_approved"] == 6
        assert result["auto_approval_rate"] == 75.0
        assert result["flagged"] == 2
        assert result["by_status"] == {"FLAGGED": 2, "EXPORTED": 8}
        assert result["blocked_amount_ttc"] == 50.0

    def test_returns_zeros_on_empty_collection(self):
        coll = _agg_coll([], [], [], [])
        with patch(
            "src.storage.documents.invoice.InvoiceDocument.get_pymongo_collection",
            return_value=coll,
        ):
            result = _run(get_kpi_mongo())
        assert result["total_invoices"] == 0
        assert result["auto_approval_rate"] == 0.0

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.invoice.InvoiceDocument.get_pymongo_collection",
            side_effect=Exception("mongo down"),
        ):
            result = _run(get_kpi_mongo())
        assert result is None


class TestMonthlySpendMongo:
    def test_maps_rows_to_monthly_shape(self):
        rows = [{"_id": "2026-01", "total_ht": 100.0, "total_ttc": 119.0, "cnt": 2, "opex": 60.0, "capex": 40.0}]
        coll = _agg_coll(rows)
        with patch(
            "src.storage.documents.invoice.InvoiceDocument.get_pymongo_collection",
            return_value=coll,
        ):
            result = _run(monthly_spend_mongo(2026))
        assert result == [{
            "month": "2026-01", "total_ht": 100.0, "total_ttc": 119.0,
            "invoice_count": 2, "opex": 60.0, "capex": 40.0,
        }]

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.invoice.InvoiceDocument.get_pymongo_collection",
            side_effect=Exception("mongo down"),
        ):
            result = _run(monthly_spend_mongo(2026))
        assert result is None


class TestBySupplierMongo:
    def test_defaults_unknown_supplier_name(self):
        rows = [{"_id": None, "total_ttc": 500.0, "total_ht": 420.0, "cnt": 3}]
        coll = _agg_coll(rows)
        with patch(
            "src.storage.documents.invoice.InvoiceDocument.get_pymongo_collection",
            return_value=coll,
        ):
            result = _run(by_supplier_mongo(None))
        assert result[0]["supplier"] == "Inconnu"
        assert result[0]["count"] == 3

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.invoice.InvoiceDocument.get_pymongo_collection",
            side_effect=Exception("mongo down"),
        ):
            result = _run(by_supplier_mongo(2026))
        assert result is None


class TestByAccountMongo:
    def test_computes_percentage_of_grand_total(self):
        rows = [
            {"_id": {"compte": "6xxx", "label": "Charges"}, "total_ht": 75.0},
            {"_id": {"compte": "2xxx", "label": None}, "total_ht": 25.0},
        ]
        coll = _agg_coll(rows)
        with patch(
            "src.storage.documents.invoice.InvoiceDocument.get_pymongo_collection",
            return_value=coll,
        ):
            result = _run(by_account_mongo(None))
        assert result[0]["pct"] == 75.0
        assert result[1]["label"] == "2xxx"  # falls back to compte when label is None

    def test_handles_empty_result_without_dividing_by_zero(self):
        coll = _agg_coll([])
        with patch(
            "src.storage.documents.invoice.InvoiceDocument.get_pymongo_collection",
            return_value=coll,
        ):
            result = _run(by_account_mongo(2026))
        assert result == []

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.invoice.InvoiceDocument.get_pymongo_collection",
            side_effect=Exception("mongo down"),
        ):
            result = _run(by_account_mongo(None))
        assert result is None


class TestAnalyticsKpisMongo:
    def test_computes_rates_and_totals(self):
        proc = [{"avg_days": 3.4}]
        counts = [{"total": 20, "rejected": 2, "reviewed": 4}]
        capex_opex = [{"capex": 300.0, "opex": 700.0}]
        coll = _agg_coll(proc, counts, capex_opex)
        coll.count_documents = AsyncMock(return_value=5)

        with patch(
            "src.storage.documents.invoice.InvoiceDocument.get_pymongo_collection",
            return_value=coll,
        ):
            result = _run(analytics_kpis_mongo(2026))

        assert result["avg_processing_days"] == 3.4
        assert result["rejection_rate"] == 10.0
        assert result["human_review_rate"] == 20.0
        assert result["total_capex_ytd"] == 300.0
        assert result["total_opex_ytd"] == 700.0
        assert result["pending_count"] == 5

    def test_handles_no_invoices_without_dividing_by_zero(self):
        coll = _agg_coll([], [], [])
        coll.count_documents = AsyncMock(return_value=0)
        with patch(
            "src.storage.documents.invoice.InvoiceDocument.get_pymongo_collection",
            return_value=coll,
        ):
            result = _run(analytics_kpis_mongo(2026))
        assert result["rejection_rate"] == 0.0
        assert result["avg_processing_days"] == 0.0

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.invoice.InvoiceDocument.get_pymongo_collection",
            side_effect=Exception("mongo down"),
        ):
            result = _run(analytics_kpis_mongo(2026))
        assert result is None


class TestGetSuiviInvoicesMongo:
    def test_returns_three_buckets(self):
        pending_payment = [SimpleNamespace(id="inv-1")]
        pending_collection = [SimpleNamespace(id="inv-2")]
        overdue = [SimpleNamespace(id="inv-3")]
        with (
            patch(
                "src.storage.documents.invoice.InvoiceDocument.find",
                side_effect=[
                    _find_chain(pending_payment),
                    _find_chain(pending_collection),
                    _find_chain(overdue),
                ],
            ),
            patch(
                "src.storage.documents.service_bridge._invoice_doc_to_record",
                side_effect=lambda d: f"record-{d.id}",
            ),
        ):
            result = _run(get_suivi_invoices_mongo())

        assert result["pending_payment"] == ["record-inv-1"]
        assert result["pending_collection"] == ["record-inv-2"]
        assert result["overdue"] == ["record-inv-3"]

    def test_returns_none_when_mongo_down(self):
        with patch(
            "src.storage.documents.invoice.InvoiceDocument.find",
            side_effect=Exception("mongo down"),
        ):
            result = _run(get_suivi_invoices_mongo())
        assert result is None
