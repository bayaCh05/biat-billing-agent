"""BCT export compliance service — Banque Centrale de Tunisie, Circulaire 2025-13.

Tracks the 120-day repatriation deadline for all export invoices.
No data is sent to cloud APIs — all logic is local.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

BCT_REPATRIATION_DAYS  = int(os.getenv("BCT_REPATRIATION_DAYS", "120"))
BCT_WARNING_THRESHOLD  = int(os.getenv("BCT_WARNING_THRESHOLD_DAYS", "20"))


def check_repatriation_status(invoice) -> dict:
    """Return BCT repatriation compliance status for a single export invoice."""
    if not invoice.is_export:
        return {"compliant": True, "reason": "domestic"}

    if invoice.repatriation_date is not None:
        days_taken = (invoice.repatriation_date - invoice.shipment_date).days if invoice.shipment_date else None
        return {"compliant": True, "status": "REPATRIATED", "days_taken": days_taken}

    if invoice.shipment_date is None:
        return {"compliant": True, "status": "PENDING", "reason": "shipment_date_not_set"}

    today = date.today()
    days_elapsed = (today - invoice.shipment_date).days
    days_remaining = BCT_REPATRIATION_DAYS - days_elapsed

    if days_elapsed > BCT_REPATRIATION_DAYS:
        return {
            "compliant": False,
            "status": "OVERDUE",
            "days_overdue": days_elapsed - BCT_REPATRIATION_DAYS,
            "action_required": "Rapatriement obligatoire — contacter BCT",
        }
    if days_remaining <= BCT_WARNING_THRESHOLD:
        return {
            "compliant": True,
            "status": "WARNING",
            "days_remaining": days_remaining,
            "action_required": "Rapatriement imminent",
        }
    return {
        "compliant": True,
        "status": "OK",
        "days_remaining": days_remaining,
    }


def check_payment_guarantee(invoice) -> dict:
    """Return required payment guarantee type based on BCT Circulaire 2025-13."""
    if not invoice.is_export:
        return {"required": False}

    if invoice.shipment_date is None or invoice.due_date is None:
        return {"required": False, "reason": "dates_not_set"}

    payment_days = (invoice.due_date - invoice.shipment_date).days

    if payment_days <= 120:
        return {"required": False, "type": "STANDARD"}
    if payment_days <= 360:
        return {
            "required": True,
            "type": "CREDOC_IRREVOCABLE",
            "message": "Crédit documentaire irrévocable requis (BCT Circulaire 2025-13)",
        }
    return {
        "required": True,
        "type": "BCT_AUTHORIZATION",
        "message": "Autorisation préalable BCT obligatoire",
    }


def generate_bct_export_report(session: Session, period_start: date, period_end: date) -> dict:
    """Build the full BCT export compliance report for a date range."""
    from src.billing.client_invoice_store import ClientInvoiceRepository

    repo = ClientInvoiceRepository(session)
    invoices = repo.list_exports(period_start, period_end)

    rows = []
    total_foreign = 0.0
    compliant_count = warning_count = overdue_count = 0

    for inv in invoices:
        rep = check_repatriation_status(inv)
        status = rep.get("status", "OK")
        days_val = rep.get("days_remaining") or (-rep.get("days_overdue", 0))

        if status == "OVERDUE":
            overdue_count += 1
        elif status == "WARNING":
            warning_count += 1
        else:
            compliant_count += 1

        if inv.foreign_currency_amount:
            total_foreign += inv.foreign_currency_amount

        rows.append({
            "invoice_number":            inv.invoice_number,
            "client_name":               inv.client_name,
            "currency":                  inv.currency,
            "foreign_amount":            inv.foreign_currency_amount,
            "exchange_rate":             inv.exchange_rate,
            "amount_tnd":                inv.amount_ttc,
            "shipment_date":             inv.shipment_date.isoformat() if inv.shipment_date else None,
            "repatriation_deadline":     inv.repatriation_deadline.isoformat() if inv.repatriation_deadline else None,
            "repatriation_date":         inv.repatriation_date.isoformat() if inv.repatriation_date else None,
            "days_remaining_or_overdue": days_val,
            "domiciliation_bank":        inv.domiciliation_bank,
            "domiciliation_number":      inv.domiciliation_number,
            "payment_guarantee_type":    inv.payment_guarantee_type,
            "status":                    status,
        })

    return {
        "period":                 f"{period_start} / {period_end}",
        "generated_at":           datetime.now(timezone.utc).isoformat(),
        "total_export_invoices":  len(invoices),
        "total_foreign_amount":   round(total_foreign, 3),
        "compliant_count":        compliant_count,
        "warning_count":          warning_count,
        "overdue_count":          overdue_count,
        "invoices":               rows,
    }
