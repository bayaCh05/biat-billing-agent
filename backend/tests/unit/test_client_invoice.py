"""Unit tests for ClientInvoice model and ClientLineItem."""
from __future__ import annotations

import pytest
from datetime import date

from src.models.client_invoice import (
    ClientInvoice,
    ClientInvoiceStatus,
    ClientLineItem,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_line(description="Maintenance SI", qty=1.0, unit_price=10000.0,
               tva_rate=19.0, compte="7061") -> ClientLineItem:
    line_total = round(qty * unit_price, 3)
    tva_amount = round(line_total * tva_rate / 100, 3)
    return ClientLineItem(
        description=description,
        quantity=qty,
        unit_price=unit_price,
        line_total=line_total,
        tva_rate=tva_rate,
        tva_amount=tva_amount,
        compte_produit=compte,
    )


def _make_invoice(lines: list[ClientLineItem] | None = None) -> ClientInvoice:
    if lines is None:
        lines = [_make_line()]
    return ClientInvoice(
        invoice_number="FAC-IT-2026-0001",
        invoice_date=date(2026, 1, 15),
        due_date=date(2026, 2, 14),
        issuer_name="BIAT IT",
        issuer_tax_id="0000999B/A/M/000",
        client_id="biat_bank",
        client_name="BIAT SA",
        client_tax_id="0000217V/A/M/000",
        line_items=lines,
    )


# ── ClientLineItem ────────────────────────────────────────────────────────────

class TestClientLineItem:
    def test_stores_all_fields(self):
        line = _make_line(qty=2.0, unit_price=5000.0)
        assert line.quantity     == 2.0
        assert line.unit_price   == 5000.0
        assert line.line_total   == pytest.approx(10000.0)
        assert line.tva_amount   == pytest.approx(1900.0)
        assert line.tva_rate     == 19.0
        assert line.compte_produit == "7061"

    def test_zero_tva_line(self):
        line = _make_line(tva_rate=0.0)
        assert line.tva_amount == 0.0
        assert line.line_total == pytest.approx(10000.0)

    def test_fractional_quantity(self):
        line = _make_line(qty=0.5, unit_price=2500.0)
        assert line.line_total == pytest.approx(1250.0)


# ── ClientInvoice amounts ────────────────────────────────────────────────────

class TestClientInvoiceAmounts:
    def test_single_line_amounts(self):
        line = _make_line(qty=1.0, unit_price=45000.0, tva_rate=19.0)
        inv  = _make_invoice([line])
        assert inv.amount_ht   == pytest.approx(45000.0)
        assert inv.tva_amount  == pytest.approx(8550.0)
        assert inv.amount_ttc  == pytest.approx(53550.0)

    def test_multi_line_amounts(self):
        lines = [
            _make_line("Maintenance", 1.0, 30000.0, tva_rate=19.0),
            _make_line("Hébergement", 1.0, 15000.0, tva_rate=19.0),
        ]
        inv = _make_invoice(lines)
        assert inv.amount_ht  == pytest.approx(45000.0)
        assert inv.tva_amount == pytest.approx(8550.0)
        assert inv.amount_ttc == pytest.approx(53550.0)

    def test_amounts_rounded_to_3dp(self):
        line = _make_line(qty=3.0, unit_price=333.333)
        inv  = _make_invoice([line])
        # 3 × 333.333 = 999.999 → rounded to 3dp
        assert inv.amount_ht  == pytest.approx(999.999)

    def test_new_invoice_with_different_lines_has_correct_amounts(self):
        line2 = _make_line(qty=2.0, unit_price=10000.0)
        inv2  = _make_invoice([line2])
        assert inv2.amount_ht == pytest.approx(20000.0)


# ── ClientInvoice defaults and identity ──────────────────────────────────────

class TestClientInvoiceDefaults:
    def test_default_status_is_draft(self):
        inv = _make_invoice()
        assert inv.status == ClientInvoiceStatus.DRAFT

    def test_id_is_uuid(self):
        from uuid import UUID
        inv = _make_invoice()
        assert isinstance(inv.id, UUID)

    def test_two_invoices_have_different_ids(self):
        inv1 = _make_invoice()
        inv2 = _make_invoice()
        assert inv1.id != inv2.id

    def test_no_source_template_by_default(self):
        inv = _make_invoice()
        assert inv.source_template_id is None

    def test_notes_optional(self):
        inv = _make_invoice()
        assert inv.notes is None

    def test_zero_amounts_with_no_lines(self):
        inv = ClientInvoice(
            invoice_number="FAC-IT-2026-0001",
            invoice_date=date(2026, 1, 1),
            due_date=date(2026, 1, 31),
            issuer_name="BIAT IT",
            issuer_tax_id="0000999B/A/M/000",
            client_id="biat_bank",
            client_name="BIAT SA",
            client_tax_id="0000217V/A/M/000",
            line_items=[],
        )
        assert inv.amount_ht  == 0.0
        assert inv.tva_amount == 0.0
        assert inv.amount_ttc == 0.0


# ── ClientInvoiceStatus ───────────────────────────────────────────────────────

class TestClientInvoiceStatus:
    def test_all_status_values_exist(self):
        assert ClientInvoiceStatus.DRAFT.value     == "draft"
        assert ClientInvoiceStatus.SENT.value      == "sent"
        assert ClientInvoiceStatus.PAID.value      == "paid"
        assert ClientInvoiceStatus.CANCELLED.value == "cancelled"

    def test_status_update_via_model_copy(self):
        inv  = _make_invoice()
        sent = inv.model_copy(update={"status": ClientInvoiceStatus.SENT})
        assert sent.status == ClientInvoiceStatus.SENT


