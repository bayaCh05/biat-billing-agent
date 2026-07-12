"""Unit tests — service_bridge.py Tier 5 (final): private helpers + the last
5 live functions not yet covered (approve/reject invoice, mark notification
read(s), sync_flagged_invoices_mirrored). Completes test coverage of all 97
functions in this file (was 127 before the dead-code removal).
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from src.storage.documents.service_bridge import (
    _asset_doc_to_pydantic,
    _client_invoice_doc_to_pydantic,
    _consumed_jh_by_project,
    _ensure_invoice_notification_native,
    _flag_to_dict,
    _get_by_str_id,
    _invoice_doc_to_record,
    _last_day_of_month,
    _parse_bound_date,
    _to_midnight_utc,
    _year_bounds,
    approve_invoice_native,
    mark_all_notifications_read_native,
    mark_notification_read_native,
    reject_invoice_native,
    sync_flagged_invoices_mirrored,
)


def _run(coro):
    return asyncio.run(coro)


_FIXED_UUID = "12345678-1234-1234-1234-123456789012"


# ── Simple pure-date helpers ───────────────────────────────────────────────────

class TestParseBoundDate:
    def test_parses_iso_date_to_utc_midnight(self):
        result = _parse_bound_date("2026-06-15")
        assert result == datetime(2026, 6, 15, tzinfo=timezone.utc)

    def test_ignores_time_component_if_present(self):
        result = _parse_bound_date("2026-06-15T23:59:59")
        assert result == datetime(2026, 6, 15, tzinfo=timezone.utc)


class TestYearBounds:
    def test_returns_jan1_to_jan1_next_year(self):
        start, end = _year_bounds(2026)
        assert start == datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert end == datetime(2027, 1, 1, tzinfo=timezone.utc)


class TestLastDayOfMonth:
    def test_handles_leap_february(self):
        assert _last_day_of_month(2028, 2) == date(2028, 2, 29)

    def test_handles_31_day_month(self):
        assert _last_day_of_month(2026, 1) == date(2026, 1, 31)


class TestToMidnightUtc:
    def test_converts_date_to_utc_midnight_datetime(self):
        result = _to_midnight_utc(date(2026, 3, 15))
        assert result == datetime(2026, 3, 15, tzinfo=timezone.utc)

    def test_returns_none_for_none_input(self):
        assert _to_midnight_utc(None) is None


# ── Small doc-shaping helpers ──────────────────────────────────────────────────

class TestGetByStrId:
    def test_queries_with_dict_filter_not_typed_get(self):
        doc_class = MagicMock()
        doc_class.find_one = AsyncMock(return_value=SimpleNamespace(id=_FIXED_UUID))
        result = _run(_get_by_str_id(doc_class, _FIXED_UUID))
        assert result.id == _FIXED_UUID
        doc_class.find_one.assert_awaited_once_with({"_id": _FIXED_UUID})


class TestFlagToDict:
    def test_converts_uuid_id_to_string(self):
        flag_id = uuid4()
        fake_flag = MagicMock()
        fake_flag.model_dump.return_value = {"id": flag_id, "flag_type": "TOTAL_MISMATCH", "resolved": False}
        result = _flag_to_dict(fake_flag)
        assert result["id"] == str(flag_id)
        assert isinstance(result["id"], str)


class TestConsumedJhByProject:
    def test_maps_project_id_to_total_consumed(self):
        coll = MagicMock()
        agg = MagicMock()
        agg.to_list = AsyncMock(return_value=[{"_id": "proj-1", "total": 42.5}])
        coll.aggregate.return_value = agg
        with patch(
            "src.storage.documents.phase.PhaseDocument.get_pymongo_collection",
            return_value=coll,
        ):
            result = _run(_consumed_jh_by_project())
        assert result == {"proj-1": 42.5}


# ── Notification read/mark-all ─────────────────────────────────────────────────

class TestMarkNotificationReadNative:
    def test_returns_none_when_not_found(self):
        with patch(
            "src.storage.documents.service_bridge._get_by_str_id",
            new=AsyncMock(return_value=None),
        ):
            result = _run(mark_notification_read_native(_FIXED_UUID))
        assert result is None

    def test_marks_read_and_returns_updated_doc(self):
        updated = SimpleNamespace(id=_FIXED_UUID, is_read=True)
        coll = MagicMock()
        coll.update_one = AsyncMock()
        with (
            patch(
                "src.storage.documents.service_bridge._get_by_str_id",
                new=AsyncMock(side_effect=[SimpleNamespace(id=_FIXED_UUID), updated]),
            ),
            patch(
                "src.storage.documents.notification.NotificationDocument.get_pymongo_collection",
                return_value=coll,
            ),
        ):
            result = _run(mark_notification_read_native(_FIXED_UUID))
        assert result is updated
        coll.update_one.assert_awaited_once_with({"_id": _FIXED_UUID}, {"$set": {"is_read": True}})


class TestMarkAllNotificationsReadNative:
    def test_marks_all_unread_as_read(self):
        coll = MagicMock()
        coll.update_many = AsyncMock()
        with patch(
            "src.storage.documents.notification.NotificationDocument.get_pymongo_collection",
            return_value=coll,
        ):
            _run(mark_all_notifications_read_native())
        coll.update_many.assert_awaited_once_with({"is_read": False}, {"$set": {"is_read": True}})


# ── Invoice review actions ──────────────────────────────────────────────────────

class TestApproveInvoiceNative:
    def test_returns_none_when_invoice_not_found(self):
        with patch(
            "src.storage.documents.service_bridge._get_by_str_id",
            new=AsyncMock(return_value=None),
        ):
            result = _run(approve_invoice_native(_FIXED_UUID, "ok", {"email": "comptable@biat-it.tn"}))
        assert result is None

    def test_resolves_open_flags_and_validates(self):
        flag = MagicMock()
        flag.model_dump.return_value = {"id": uuid4(), "resolved": False, "flag_type": "TOTAL_MISMATCH"}
        doc = SimpleNamespace(id=_FIXED_UUID, status="FLAGGED", flags=[flag])
        updated = SimpleNamespace(id=_FIXED_UUID, status="VALIDATED")
        coll = MagicMock()
        coll.update_one = AsyncMock()
        with (
            patch(
                "src.storage.documents.service_bridge._get_by_str_id",
                new=AsyncMock(side_effect=[doc, updated]),
            ),
            patch(
                "src.storage.documents.invoice.InvoiceDocument.get_pymongo_collection",
                return_value=coll,
            ),
            patch(
                "src.storage.documents.service_bridge._create_audit_log_native",
                new=AsyncMock(),
            ) as mock_audit,
        ):
            result = _run(approve_invoice_native(_FIXED_UUID, "RAS", {"email": "comptable@biat-it.tn"}))

        assert result is updated
        update = coll.update_one.call_args[0][1]["$set"]
        assert update["status"] == "VALIDATED"
        assert update["flags"][0]["resolved"] is True
        assert update["flags"][0]["resolved_by"] == "human"
        mock_audit.assert_awaited_once()


class TestRejectInvoiceNative:
    def test_returns_none_when_invoice_not_found(self):
        with patch(
            "src.storage.documents.service_bridge._get_by_str_id",
            new=AsyncMock(return_value=None),
        ):
            result = _run(reject_invoice_native(_FIXED_UUID, "doublon", {"email": "comptable@biat-it.tn"}))
        assert result is None

    def test_sets_status_rejected_and_logs_audit(self):
        doc = SimpleNamespace(id=_FIXED_UUID, status="FLAGGED")
        updated = SimpleNamespace(id=_FIXED_UUID, status="REJECTED")
        coll = MagicMock()
        coll.update_one = AsyncMock()
        with (
            patch(
                "src.storage.documents.service_bridge._get_by_str_id",
                new=AsyncMock(side_effect=[doc, updated]),
            ),
            patch(
                "src.storage.documents.invoice.InvoiceDocument.get_pymongo_collection",
                return_value=coll,
            ),
            patch(
                "src.storage.documents.service_bridge._create_audit_log_native",
                new=AsyncMock(),
            ) as mock_audit,
        ):
            result = _run(reject_invoice_native(_FIXED_UUID, "doublon", {"email": "comptable@biat-it.tn"}))

        assert result is updated
        update = coll.update_one.call_args[0][1]["$set"]
        assert update["status"] == "REJECTED"
        assert update["human_review_notes"] == "doublon"
        mock_audit.assert_awaited_once()


# ── Flagged-invoice notification sync (100% Mongo — InvoiceDocument + NotificationDocument) ─

class TestSyncFlaggedInvoicesMirrored:
    def test_creates_notification_for_each_flagged_invoice_needing_review(self):
        needs_review = SimpleNamespace(
            id=uuid4(), human_review_required=True, status="FLAGGED",
            issuer_name="Ooredoo",
        )
        fake_find = MagicMock(to_list=AsyncMock(return_value=[needs_review]))

        with (
            patch("src.storage.documents.invoice.InvoiceDocument.find", return_value=fake_find) as mock_find,
            patch(
                "src.storage.documents.service_bridge._ensure_invoice_notification_native",
                new=AsyncMock(),
            ) as mock_ensure,
        ):
            _run(sync_flagged_invoices_mirrored())

        query = mock_find.call_args[0][0]
        assert query["human_review_required"] is True
        assert set(query["status"]["$nin"]) == {"REJECTED", "ERROR"}
        mock_ensure.assert_awaited_once_with(needs_review.id, "Ooredoo", "FLAGGED")

    def test_no_matching_invoices_is_a_noop(self):
        fake_find = MagicMock(to_list=AsyncMock(return_value=[]))
        with (
            patch("src.storage.documents.invoice.InvoiceDocument.find", return_value=fake_find),
            patch(
                "src.storage.documents.service_bridge._ensure_invoice_notification_native",
                new=AsyncMock(),
            ) as mock_ensure,
        ):
            _run(sync_flagged_invoices_mirrored())
        mock_ensure.assert_not_awaited()


class TestEnsureInvoiceNotificationNative:
    def test_skips_when_notification_already_exists(self):
        with (
            patch(
                "src.storage.documents.notification.NotificationDocument.find_one",
                new=AsyncMock(return_value=SimpleNamespace(id="existing-notif")),
            ),
            patch(
                "src.storage.documents.notification.NotificationDocument.get_pymongo_collection",
            ) as mock_coll,
        ):
            _run(_ensure_invoice_notification_native(uuid4(), "Ooredoo", "FLAGGED"))
        mock_coll.return_value.insert_one.assert_not_called()

    def test_creates_notification_when_absent(self):
        invoice_id = uuid4()
        coll = MagicMock()
        coll.insert_one = AsyncMock()
        with (
            patch(
                "src.storage.documents.notification.NotificationDocument.find_one",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "src.storage.documents.notification.NotificationDocument.get_pymongo_collection",
                return_value=coll,
            ),
        ):
            _run(_ensure_invoice_notification_native(invoice_id, "Ooredoo", "FLAGGED"))

        coll.insert_one.assert_awaited_once()
        doc = coll.insert_one.call_args[0][0]
        assert doc["type"] == "INVOICE_FLAGGED"
        assert doc["invoice_id"] == str(invoice_id)
        assert doc["is_read"] is False

    def test_escalated_status_uses_escalated_notif_type(self):
        coll = MagicMock()
        coll.insert_one = AsyncMock()
        with (
            patch(
                "src.storage.documents.notification.NotificationDocument.find_one",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "src.storage.documents.notification.NotificationDocument.get_pymongo_collection",
                return_value=coll,
            ),
        ):
            _run(_ensure_invoice_notification_native(uuid4(), "Ooredoo", "ESCALATED"))
        doc = coll.insert_one.call_args[0][0]
        assert doc["type"] == "INVOICE_ESCALATED"


# ── Doc -> Pydantic converters ──────────────────────────────────────────────────

def _fake_invoice_doc(**overrides):
    base = dict(
        id=uuid4(), file_hash="abc123", raw_file_path="/tmp/a.pdf", file_mime_type="application/pdf",
        direction="SUPPLIER", status="VALIDATED", extraction_method=None, retry_count=0, last_error=None,
        currency="TND", raw_extracted_json=None, cost_catalog_id=None, accounting_compte=None,
        accounting_label=None, charge_nature=None, charge_type=None, matched_po_id=None,
        matched_contract_id=None, matched_client_id=None, payment_term_days=None,
        classification_reason=None, classification_pass=None, human_review_required=False,
        human_review_notes=None, reviewed_by=None, reviewed_at=None,
        received_at=datetime.now(timezone.utc), extracted_at=None, classified_at=None,
        validated_at=None, exported_at=None, export_reference=None, paid_at=None, collected_at=None,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        issuer_name="TECHNOVA SARL", issuer_name_conf=0.9,
        issuer_tax_id=None, issuer_tax_id_conf=None,
        recipient_name=None, recipient_name_conf=None,
        recipient_tax_id=None, recipient_tax_id_conf=None,
        invoice_number="FAC-2026-0001", invoice_number_conf=0.95,
        invoice_date=date(2026, 1, 1), invoice_date_conf=0.9,
        due_date=None, due_date_conf=None,
        amount_ht=1000.0, amount_ht_conf=0.9,
        tva_rate=19.0, tva_rate_conf=0.9,
        tva_amount=190.0, tva_amount_conf=0.9,
        amount_ttc=1190.0, amount_ttc_conf=0.9,
        line_items=[], flags=[],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestInvoiceDocToRecord:
    def test_maps_scalar_and_confidence_fields(self):
        doc = _fake_invoice_doc()
        record = _invoice_doc_to_record(doc)
        assert record.file_hash == "abc123"
        assert record.issuer_name.value == "TECHNOVA SARL"
        assert record.issuer_name.confidence == 0.9
        assert record.amount_ttc.value == 1190.0

    def test_maps_line_items_and_flags(self):
        line_item = SimpleNamespace(
            line_number=1, description="Licence", quantity=1, unit_price=1000.0,
            line_total=1000.0, tva_rate=19.0,
        )
        flag = SimpleNamespace(
            flag_type="TOTAL_MISMATCH", severity="WARNING", field_name="amount_ttc",
            message="...", resolved=False, resolved_at=None, resolved_by=None,
        )
        doc = _fake_invoice_doc(line_items=[line_item], flags=[flag])
        record = _invoice_doc_to_record(doc)
        assert len(record.line_items) == 1
        assert record.line_items[0].description == "Licence"
        assert len(record.flags) == 1
        assert record.flags[0].resolved is False


class TestAssetDocToPydantic:
    def test_maps_fields(self):
        doc = SimpleNamespace(
            id=uuid4(), designation="Serveur Dell", compte_immobilisation="2183",
            compte_amortissement="28183", acquisition_date=date(2026, 1, 1),
            acquisition_cost_ht=15000.0, useful_life_years=5, depreciation_method="linear",
            supplier_invoice_id=None, amortization_source=None, notes=None,
            created_at=datetime.now(timezone.utc),
        )
        asset = _asset_doc_to_pydantic(doc)
        assert asset.designation == "Serveur Dell"
        assert asset.acquisition_cost_ht == 15000.0
        assert asset.notes == ""  # None -> "" per source


class TestClientInvoiceDocToPydantic:
    def test_maps_fields_and_line_items(self):
        line = SimpleNamespace(
            description="Prestation IT", quantity=1, unit_price=500.0, line_total=500.0,
            tva_rate=19.0, tva_amount=95.0, compte_produit="706",
        )
        doc = SimpleNamespace(
            id=uuid4(), invoice_number="FAC-IT-2026-0001", invoice_date=date(2026, 1, 1),
            due_date=date(2026, 2, 1), issuer_name="BIAT IT", issuer_tax_id="0000217V",
            issuer_address=None, client_id="client-1", client_name="Filiale X",
            client_tax_id="123", client_address=None, line_items=[line],
            amount_ht=500.0, tva_amount=95.0, amount_ttc=595.0, status="draft",
            source_template_id="tpl-1", notes=None, pdf_path=None,
            created_at=datetime.now(timezone.utc), sent_at=None, paid_at=None,
        )
        invoice = _client_invoice_doc_to_pydantic(doc)
        assert invoice.invoice_number == "FAC-IT-2026-0001"
        assert invoice.amount_ttc == 595.0
        assert len(invoice.line_items) == 1
        assert invoice.line_items[0].description == "Prestation IT"
