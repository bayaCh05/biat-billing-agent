"""Seed BCT export compliance demo data.

Creates 3 export client invoices with different BCT repatriation statuses:
  - FAC-IT-2026-0010 (EUR, OVERDUE)
  - FAC-IT-2026-0011 (USD, WARNING — <20 days to deadline)
  - FAC-IT-2026-0012 (GBP, OK — >20 days to deadline)

Idempotent: skips invoices that already exist.
"""
from __future__ import annotations

import sys
import os
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATABASE_URL", "sqlite:///./data/invoices.db")

from src.storage.db import build_engine, build_session_factory
from src.billing.client_invoice_store import ClientInvoiceORM, ClientLineItemORM

# ── Configuration ─────────────────────────────────────────────────────────────

BCT_REPATRIATION_DAYS = int(os.getenv("BCT_REPATRIATION_DAYS", "120"))
BCT_WARNING_THRESHOLD = int(os.getenv("BCT_WARNING_THRESHOLD_DAYS", "20"))

TODAY = date.today()

INVOICES = [
    {
        "invoice_number": "FAC-IT-2026-0010",
        "currency": "EUR",
        "is_export": True,
        "client_name": "Société Tunisienne d'Export SA",
        "client_id": "STE-001",
        "client_tax_id": "1234567A/P/M/000",
        "client_address": "Zone Industrielle Bir El Bey, Ben Arous, Tunisie",
        "invoice_date": date(2026, 2, 1),
        "due_date": date(2026, 5, 1),
        "shipment_date": TODAY - timedelta(days=BCT_REPATRIATION_DAYS + 30),
        # deadline = shipment + 120 → past by 30 days → OVERDUE
        "repatriation_date": None,
        "foreign_currency_amount": 8500.0,
        "exchange_rate": 3.32,
        "domiciliation_bank": "BIAT Siège Tunis",
        "domiciliation_number": "DOM-2026-0010",
        "payment_guarantee_type": "STANDARD",
        "status": "sent",
        "lines": [
            {
                "description": "Conseil en transformation numérique – Phase 1",
                "quantity": 10.0,
                "unit_price": 850.0,
                "tva_rate": 19.0,
            }
        ],
    },
    {
        "invoice_number": "FAC-IT-2026-0011",
        "currency": "USD",
        "is_export": True,
        "client_name": "Atlas International SARL",
        "client_id": "ATL-002",
        "client_tax_id": "7654321B/P/M/000",
        "client_address": "Tour Atlas, Boulevard Mohammed V, Casablanca, Maroc",
        "invoice_date": date(2026, 3, 15),
        "due_date": date(2026, 6, 15),
        "shipment_date": TODAY - timedelta(days=BCT_REPATRIATION_DAYS - BCT_WARNING_THRESHOLD + 5),
        # deadline = shipment + 120 → 15 days remaining → WARNING
        "repatriation_date": None,
        "foreign_currency_amount": 12000.0,
        "exchange_rate": 3.07,
        "domiciliation_bank": "BIAT Siège Tunis",
        "domiciliation_number": "DOM-2026-0011",
        "payment_guarantee_type": "CREDOC_IRREVOCABLE",
        "status": "sent",
        "lines": [
            {
                "description": "Développement plateforme e-banking – Module paiement",
                "quantity": 15.0,
                "unit_price": 800.0,
                "tva_rate": 19.0,
            },
            {
                "description": "Formation utilisateurs (5 jours)",
                "quantity": 5.0,
                "unit_price": 480.0,
                "tva_rate": 19.0,
            },
        ],
    },
    {
        "invoice_number": "FAC-IT-2026-0012",
        "currency": "GBP",
        "is_export": True,
        "client_name": "Maghreb Tech Europe Ltd",
        "client_id": "MTE-003",
        "client_tax_id": "GB123456789",
        "client_address": "22 King Street, London EC2V 8RT, United Kingdom",
        "invoice_date": date(2026, 6, 1),
        "due_date": date(2026, 9, 1),
        "shipment_date": TODAY - timedelta(days=30),
        # deadline = shipment + 120 → 90 days remaining → OK
        "repatriation_date": None,
        "foreign_currency_amount": 5200.0,
        "exchange_rate": 3.96,
        "domiciliation_bank": "BIAT Siège Tunis",
        "domiciliation_number": "DOM-2026-0012",
        "payment_guarantee_type": "STANDARD",
        "status": "sent",
        "lines": [
            {
                "description": "Audit sécurité infrastructure bancaire",
                "quantity": 8.0,
                "unit_price": 650.0,
                "tva_rate": 19.0,
            },
        ],
    },
]

ISSUER = {
    "name": "BIAT IT",
    "tax_id": "0000000A/M/A/000",
    "address": "Rue de la Bourse, Tunis 1000, Tunisie",
}


def _build_orm(spec: dict) -> ClientInvoiceORM:
    lines_spec = spec.pop("lines")
    ship = spec["shipment_date"]
    repatriation_deadline = ship + timedelta(days=BCT_REPATRIATION_DAYS) if ship else None

    # Compute totals from lines
    amount_ht = 0.0
    tva_amount = 0.0
    orm_lines = []
    invoice_id = uuid4()

    for ls in lines_spec:
        line_total = round(ls["quantity"] * ls["unit_price"], 3)
        line_tva = round(line_total * ls["tva_rate"] / 100, 3)
        amount_ht += line_total
        tva_amount += line_tva
        orm_lines.append(ClientLineItemORM(
            invoice_id=invoice_id,
            description=ls["description"],
            quantity=ls["quantity"],
            unit_price=ls["unit_price"],
            line_total=line_total,
            tva_rate=ls["tva_rate"],
            tva_amount=line_tva,
            compte_produit="7061",
        ))

    amount_ht = round(amount_ht, 3)
    tva_amount = round(tva_amount, 3)
    amount_ttc = round(amount_ht + tva_amount, 3)

    orm = ClientInvoiceORM(
        id=invoice_id,
        invoice_number=spec["invoice_number"],
        invoice_date=spec["invoice_date"],
        due_date=spec["due_date"],
        issuer_name=ISSUER["name"],
        issuer_tax_id=ISSUER["tax_id"],
        issuer_address=ISSUER["address"],
        client_id=spec["client_id"],
        client_name=spec["client_name"],
        client_tax_id=spec["client_tax_id"],
        client_address=spec.get("client_address", ""),
        amount_ht=amount_ht,
        tva_amount=tva_amount,
        amount_ttc=amount_ttc,
        status=spec["status"],
        created_at=datetime.now(timezone.utc),
        sent_at=datetime.now(timezone.utc),
        # BCT fields
        currency=spec["currency"],
        is_export=spec["is_export"],
        domiciliation_bank=spec.get("domiciliation_bank"),
        domiciliation_number=spec.get("domiciliation_number"),
        shipment_date=spec["shipment_date"],
        repatriation_deadline=repatriation_deadline,
        repatriation_date=spec.get("repatriation_date"),
        payment_guarantee_type=spec.get("payment_guarantee_type"),
        foreign_currency_amount=spec.get("foreign_currency_amount"),
        exchange_rate=spec.get("exchange_rate"),
    )
    orm.line_items = orm_lines
    return orm


def main() -> None:
    engine = build_engine("sqlite:///./data/invoices.db")
    SessionFactory = build_session_factory(engine)

    with SessionFactory() as session:
        seeded = 0
        skipped = 0
        for spec in INVOICES:
            number = spec["invoice_number"]
            existing = session.execute(
                __import__("sqlalchemy").select(ClientInvoiceORM).where(
                    ClientInvoiceORM.invoice_number == number
                )
            ).scalar_one_or_none()
            if existing:
                print(f"  SKIP  {number} (already exists)")
                skipped += 1
                continue

            ship = spec.get("shipment_date")
            deadline = (ship + timedelta(days=BCT_REPATRIATION_DAYS)) if ship else None
            if deadline:
                days_left = (deadline - TODAY).days
                bct_status = (
                    "OVERDUE" if days_left < 0
                    else "WARNING" if days_left < BCT_WARNING_THRESHOLD
                    else "OK"
                )
            else:
                bct_status = "PENDING"

            orm = _build_orm(dict(spec))  # spec is consumed by pop, copy first
            session.add(orm)
            print(f"  SEED  {number} ({spec['currency']}) → BCT:{bct_status}"
                  f" ship={ship} deadline={deadline} ({days_left if deadline else '?'} days left)")
            seeded += 1

        session.commit()
        print(f"\nDone: {seeded} seeded, {skipped} skipped.")


if __name__ == "__main__":
    main()
