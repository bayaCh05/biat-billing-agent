"""Seed monthly supplier invoices (Jan–Jun 2026) to populate budget actuals.

Creates realistic JOURNALED invoices for the major budget catalog lines so the
Budget tab shows meaningful bar charts (budget vs réel) with varied states:
  - On budget  : salaires, loyers, gardiennage, télécoms
  - Slightly over: charges_sociales, licences_saas, honoraires
  - Well under  : formation_personnel, infogerance_sla
  - No actuals  : CAPEX lines (materiel_informatique already seeded separately)

Usage:
    python scripts/seed_budget_actuals.py

Idempotent — skips any (catalog_id, month) pair whose file_hash already exists.
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).parent.parent))

# api.auth must be imported first (before src.storage.mongodb) — it's what
# loads .env (MONGODB_URI included), which mongodb.py reads as a module-level
# constant at import time.
import api.auth  # noqa: F401
from src.storage.mongodb import close_mongodb, init_beanie
from src.storage.sync_mongo_repository import SyncMongoInvoiceRepository, _get_db
from src.models.invoice import ConfidenceField, InvoiceRecord
from src.models.enums import InvoiceDirection, InvoiceStatus

TVA = 0.19

def _ttc(ht: float) -> float:
    return round(ht * (1 + TVA), 3)

def _hash(label: str, month: int) -> str:
    return hashlib.sha256(f"seed-budget-{label}-{month}".encode()).hexdigest()[:64]

def _cf(value, conf: float = 0.99) -> ConfidenceField:
    return ConfidenceField(value=value, confidence=conf)

# Each entry: (catalog_id, issuer_name, monthly_ht per month Jan-Jun)
# Budget YTD Jan-Jun from YAML for reference is in comments
LINES = [
    # ── Salaires : budget 510 000 TND — on budget ────────────────────────────
    # 85 000/mois — on paie réellement 84 500-86 000
    (
        "salaires", "BIAT IT — Paie interne",
        [84500, 84500, 85000, 85000, 86000, 85500],
    ),
    # ── Charges sociales : budget 132 600 — légèrement au-dessus ─────────────
    # 22 100/mois — réel ~22 800 (quelques heures sup)
    (
        "charges_sociales", "CNSS Tunisie",
        [22800, 22800, 22800, 22800, 22800, 23100],
    ),
    # ── Avantages en nature : budget 21 000 — conforme ────────────────────────
    # 3 500/mois
    (
        "avantages_nature", "BIAT IT — Avantages",
        [3500, 3500, 3500, 3500, 3500, 3500],
    ),
    # ── Loyers immobiliers : budget 72 000 — conforme ─────────────────────────
    # 12 000/mois
    (
        "loyers_immobiliers", "Société Foncière Tunis",
        [12000, 12000, 12000, 12000, 12000, 12000],
    ),
    # ── Personnel externe : budget 120 000 — légèrement dépassé ──────────────
    # 20 000/mois — recours accru aux prestataires
    (
        "personnel_externe", "Consulting IT Partners",
        [20000, 21500, 22000, 21500, 22500, 23000],
    ),
    # ── Infogérance & SLA : budget 60 000 — sous-consommé ─────────────────────
    # 10 000/mois — certains tickets non facturés encore
    (
        "infogerance_sla", "Sopra Steria Tunisie",
        [10000, 10000, 8500, 10000, 8500, 0],  # 0 = pas encore facturé juin
    ),
    # ── Honoraires & conseil : budget 36 000 — légèrement dépassé ─────────────
    # T1 5k+5k+8k=18k, T2 5k+5k+8k=18k → budget 36k, réel 38k
    (
        "honoraires_conseil", "Cabinet KPMG Tunisie",
        [5500, 5500, 9000, 6000, 5500, 7000],
    ),
    # ── Licences SaaS : budget 82 000 — dépassement sur T2 ────────────────────
    # Budget: 8+8+25+8+8+25 = 82k, réel 89k (renouvellements sous-estimés)
    (
        "licences_saas", "Microsoft Maghreb",
        [9000, 9000, 27000, 9500, 9500, 25000],
    ),
    # ── Assurance multirisques : budget 7 200 — conforme ─────────────────────
    (
        "assurance_multirisques", "STAR Assurances",
        [1200, 1200, 1200, 1200, 1200, 1200],
    ),
    # ── Assurance RC pro : budget 4 800 — conforme ────────────────────────────
    (
        "assurance_rc_pro", "GAT Assurances",
        [800, 800, 800, 800, 800, 800],
    ),
    # ── Nettoyage & entretien : budget 10 800 — conforme ─────────────────────
    (
        "nettoyage_entretien", "Propretex Tunisie",
        [1800, 1800, 1800, 1800, 1800, 1800],
    ),
    # ── Frais déplacement : budget 9 000 — légèrement sous ───────────────────
    (
        "frais_deplacement", "BIAT IT — Notes de frais",
        [1200, 1400, 1500, 1300, 1100, 1000],
    ),
    # ── Refacturation de charges : budget 30 000 — conforme ──────────────────
    (
        "refacturation_charges", "BIAT Holding — Refacturation",
        [5000, 5000, 5000, 5000, 5000, 5000],
    ),
]

MONTHS = [1, 2, 3, 4, 5, 6]
MONTH_DAY = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30}


async def main() -> None:
    if not await init_beanie():
        print("MONGODB_URI non défini ou connexion impossible — abandon.")
        sys.exit(1)

    inv_repo = SyncMongoInvoiceRepository()
    created = 0
    skipped = 0

    for catalog_id, issuer, monthly_ht in LINES:
        for i, month in enumerate(MONTHS):
            ht = monthly_ht[i]
            if ht == 0:
                skipped += 1
                continue

            h = _hash(catalog_id, month)
            if inv_repo.get_by_hash(h) is not None:
                skipped += 1
                continue

            inv = InvoiceRecord(
                file_hash=h,
                raw_file_path=f"seeds/budget/{catalog_id}_{month:02d}_2026.pdf",
                direction=InvoiceDirection.SUPPLIER,
                status=InvoiceStatus.JOURNALED,
                issuer_name=_cf(issuer),
                invoice_date=_cf(date(2026, month, MONTH_DAY[month])),
                invoice_number=_cf(f"{catalog_id.upper()[:8]}-2026-{month:02d}"),
                amount_ht=_cf(float(ht)),
                tva_rate=_cf(TVA * 100),
                tva_amount=_cf(round(ht * TVA, 3)),
                amount_ttc=_cf(_ttc(ht)),
                currency="TND",
                cost_catalog_id=catalog_id,
                classification_pass="A",
                human_review_required=False,
            )
            inv_repo.save(inv)
            created += 1

    print(f"\n✓ {created} factures créées, {skipped} ignorées (déjà présentes ou montant 0).")

    # Print summary
    db = _get_db()
    rows = db["invoices"].aggregate([
        {"$match": {"direction": "SUPPLIER", "cost_catalog_id": {"$ne": None}}},
        {"$group": {"_id": "$cost_catalog_id", "total": {"$sum": "$amount_ht"}}},
        {"$sort": {"total": -1}},
    ])
    print(f"\nActuels par catégorie (Jan–Juin 2026) :")
    for r in rows:
        print(f"  {r['_id']:35} {r['total']:>10.0f} TND HT")

    await close_mongodb()


if __name__ == "__main__":
    asyncio.run(main())
