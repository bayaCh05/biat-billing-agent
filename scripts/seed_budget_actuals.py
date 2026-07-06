"""Seed monthly supplier invoices (Jan–Jun 2026) to populate budget actuals.

Creates realistic JOURNALED invoices for the major budget catalog lines so the
Budget tab shows meaningful bar charts (budget vs réel) with varied states:
  - On budget  : salaires, loyers, gardiennage, télécoms
  - Slightly over: charges_sociales, licences_saas, honoraires
  - Well under  : formation_personnel, infogerance_sla
  - No actuals  : CAPEX lines (materiel_informatique already seeded separately)

Usage:
    python scripts/seed_budget_actuals.py
"""
from __future__ import annotations

import hashlib
import sys
from datetime import date
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.db import build_engine, build_session_factory, init_db
from src.storage.orm_models import InvoiceORM

TVA = 0.19

def _ttc(ht: float) -> float:
    return round(ht * (1 + TVA), 3)

def _hash(label: str, month: int) -> str:
    return hashlib.sha256(f"seed-budget-{label}-{month}".encode()).hexdigest()[:64]

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


def main() -> None:
    engine = build_engine("sqlite:///./data/invoices.db")
    init_db(engine)
    sf = build_session_factory(engine)

    created = 0
    skipped = 0

    with sf() as session:
        for catalog_id, issuer, monthly_ht in LINES:
            for i, month in enumerate(MONTHS):
                ht = monthly_ht[i]
                if ht == 0:
                    skipped += 1
                    continue

                h = _hash(catalog_id, month)
                existing = session.query(InvoiceORM).filter_by(file_hash=h).first()
                if existing:
                    skipped += 1
                    continue

                inv = InvoiceORM(
                    file_hash=h,
                    raw_file_path=f"seeds/budget/{catalog_id}_{month:02d}_2026.pdf",
                    direction="SUPPLIER",
                    status="JOURNALED",
                    issuer_name=issuer,
                    issuer_name_conf=0.99,
                    invoice_date=date(2026, month, MONTH_DAY[month]),
                    invoice_date_conf=0.99,
                    invoice_number=f"{catalog_id.upper()[:8]}-2026-{month:02d}",
                    invoice_number_conf=0.99,
                    amount_ht=float(ht),
                    amount_ht_conf=0.99,
                    tva_rate=TVA * 100,
                    tva_rate_conf=0.99,
                    tva_amount=round(ht * TVA, 3),
                    tva_amount_conf=0.99,
                    amount_ttc=_ttc(ht),
                    amount_ttc_conf=0.99,
                    currency="TND",
                    cost_catalog_id=catalog_id,
                    classification_pass="A",
                    human_review_required=False,
                )
                session.add(inv)
                created += 1

        session.commit()

    print(f"\n✓ {created} factures créées, {skipped} ignorées (déjà présentes ou montant 0).")

    # Print summary
    engine2 = build_engine("sqlite:///./data/invoices.db")
    sf2 = build_session_factory(engine2)
    from sqlalchemy import select, func
    with sf2() as s:
        rows = s.execute(
            select(InvoiceORM.cost_catalog_id, func.sum(InvoiceORM.amount_ht).label("total"))
            .where(InvoiceORM.direction == "SUPPLIER", InvoiceORM.cost_catalog_id.isnot(None))
            .group_by(InvoiceORM.cost_catalog_id)
            .order_by(func.sum(InvoiceORM.amount_ht).desc())
        ).all()
        print(f"\nActuels par catégorie (Jan–Juin 2026) :")
        for r in rows:
            print(f"  {r.cost_catalog_id:35} {r.total:>10.0f} TND HT")


if __name__ == "__main__":
    main()
