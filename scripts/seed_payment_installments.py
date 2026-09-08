"""One-off demo seed — populate payment_installments for a couple of already-
seeded invoices, so the échéancier and AuditAgent's cross-checks
(LATE_INSTALLMENT_NOT_FLAGGED, MISSING_INSTALLMENT_PLAN) have real data to
show in a live demo. Confirmed live (2026-09-08, see session notes): 0 of
102 seeded invoices had payment_term_days set at all, so payment_installments
was empty and these checks could never fire.

Mirrors AccountingAgent._create_payment_schedule()'s exact algorithm (same
formula for installment count/amounts/due dates) rather than importing the
private method — this is a one-off manual seed script, not part of the real
pipeline; if that method's formula ever changes, this script's output may
drift, which is acceptable here (same convention as the other one-off
rebaseline/backfill scripts in this directory).

Picks 2 real JOURNALED invoices with no existing payment_term_days:
  - One left PENDING and overdue on purpose, to demonstrate a genuine
    "late installment" the échéancier/AuditAgent should catch.
  - One marked fully PAID, to demonstrate the healthy/settled case too.

Idempotent — skips any invoice that already has payment_term_days set.

Usage:
    python scripts/seed_payment_installments.py            # applies
    python scripts/seed_payment_installments.py --dry-run  # preview only
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).parent.parent))

import api.auth  # noqa: F401  (charge .env, même convention que les autres scripts)

from src.storage.sync_mongo_repository import _get_db, save_payment_installments_sync

_INSTALL_PERIOD = 30  # PAYMENT_INSTALLMENT_PERIOD_DAYS default — see accounting_agent.py


def _installment_rows(invoice_id: str, received_at: datetime, amount_ttc: float, term_days: int) -> list[dict]:
    period = _INSTALL_PERIOD
    n_full = term_days // period
    remainder = term_days % period
    total = n_full + (1 if remainder > 0 else 0)
    base_amount = round(amount_ttc / total, 3)

    rows = []
    for i in range(1, total + 1):
        period_days = period if (i < total or remainder == 0) else remainder
        cumulative_days = period * (i - 1) + period_days
        due_date = (received_at + timedelta(days=cumulative_days)).date()
        rows.append({
            "invoice_id": invoice_id,
            "installment_number": i,
            "total_installments": total,
            "base_amount": base_amount,
            "current_amount": base_amount,
            "due_date": due_date,
        })
    return rows


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    invoices = _get_db()["invoices"]
    installments = _get_db()["payment_installments"]

    candidates = list(invoices.find(
        {"status": "JOURNALED", "payment_term_days": None},
        {"_id": 1, "received_at": 1, "amount_ttc": 1, "issuer_name": 1},
    ).limit(2))

    if len(candidates) < 2:
        print(f"Seulement {len(candidates)} facture(s) éligible(s) (JOURNALED, sans payment_term_days) — rien à faire.")
        return

    overdue_inv, paid_inv = candidates[0], candidates[1]
    print(f"Facture en retard (démo) : {overdue_inv['_id']} — {overdue_inv.get('issuer_name')}")
    print(f"Facture payée (démo)     : {paid_inv['_id']} — {paid_inv.get('issuer_name')}")

    if dry_run:
        print("(--dry-run : aucune écriture effectuée)")
        return

    now = datetime.now(timezone.utc)

    # ── Facture 1 : échéance en retard, jamais payée — reste PENDING ──────────
    invoices.update_one({"_id": overdue_inv["_id"]}, {"$set": {"payment_term_days": 30}})
    rows = _installment_rows(overdue_inv["_id"], overdue_inv["received_at"], overdue_inv["amount_ttc"], 30)
    ids = save_payment_installments_sync(rows)
    print(f"✓ {len(ids)} échéance(s) créée(s) pour {overdue_inv['_id']} (statut PENDING, en retard)")

    # ── Facture 2 : échéancier réglé intégralement ────────────────────────────
    invoices.update_one({"_id": paid_inv["_id"]}, {"$set": {"payment_term_days": 60}})
    rows = _installment_rows(paid_inv["_id"], paid_inv["received_at"], paid_inv["amount_ttc"], 60)
    ids = save_payment_installments_sync(rows)
    for _id, row in zip(ids, rows):
        installments.update_one({"_id": _id}, {"$set": {
            "status": "PAID",
            "paid_date": now,
            "paid_amount": row["current_amount"],
        }})
    print(f"✓ {len(ids)} échéance(s) créée(s) et marquée(s) PAID pour {paid_inv['_id']}")


if __name__ == "__main__":
    main()
