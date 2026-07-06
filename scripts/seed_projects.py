#!/usr/bin/env python3
"""Seed 3 demo projects + 9 phases into the existing database (append-safe)."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from src.storage.db import build_engine, build_session_factory, init_db
from src.storage.orm_models_projects import CharteProjetORM, PhaseORM

DB_URL = "sqlite:///./data/invoices.db"

PROJECTS = [
    CharteProjetORM(
        id="CHR-2026-0001",
        project_id="PRJ-CBK",
        project_name="Migration Core Banking System",
        client="BIAT",
        valid_from=date(2026, 1, 5),
        valid_until=date(2026, 12, 31),
        budget_jh=120.0,
        taux_jh=850.0,
        is_active=True,
    ),
    CharteProjetORM(
        id="CHR-2026-0002",
        project_id="PRJ-IC",
        project_name="Infrastructure Cloud Hybride",
        client="BIAT",
        valid_from=date(2026, 2, 1),
        valid_until=date(2026, 9, 30),
        budget_jh=80.0,
        taux_jh=850.0,
        is_active=True,
    ),
    CharteProjetORM(
        id="CHR-2026-0003",
        project_id="PRJ-PCD",
        project_name="Portail Client Digital",
        client="BIAT",
        valid_from=date(2026, 3, 1),
        valid_until=date(2026, 11, 30),
        budget_jh=100.0,
        taux_jh=850.0,
        is_active=True,
    ),
]

PHASES = [
    # PRJ-CBK — 3 phases
    PhaseORM(id="PH-CBK-001", project_id="PRJ-CBK", name="Analyse & spécifications",
             description="Cadrage fonctionnel, recueil besoins, rédaction cahier des charges",
             planned_jh=20.0, consumed_jh=20.0, status="closed",
             closed_date=date(2026, 3, 31), livrables='["Cahier des charges", "Matrice des exigences"]'),
    PhaseORM(id="PH-CBK-002", project_id="PRJ-CBK", name="Architecture technique",
             description="Conception architecture cible, choix technologiques, prototypage",
             planned_jh=18.0, consumed_jh=18.0, status="closed",
             closed_date=date(2026, 5, 15), livrables='["Dossier d\'architecture", "POC validé"]'),
    PhaseORM(id="PH-CBK-003", project_id="PRJ-CBK", name="Développement & tests",
             description="Développement modules, tests unitaires et intégration",
             planned_jh=82.0, consumed_jh=24.0, status="open",
             closed_date=None, livrables='[]'),
    # PRJ-IC — 3 phases
    PhaseORM(id="PH-IC-001", project_id="PRJ-IC", name="Audit infrastructure existante",
             description="Inventaire, audit sécurité, identification dépendances",
             planned_jh=15.0, consumed_jh=15.0, status="closed",
             closed_date=date(2026, 3, 15), livrables='["Rapport d\'audit", "Cartographie SI"]'),
    PhaseORM(id="PH-IC-002", project_id="PRJ-IC", name="POC Cloud hybride",
             description="Mise en place environnement test, migration pilote 3 serveurs",
             planned_jh=28.0, consumed_jh=28.0, status="closed",
             closed_date=date(2026, 5, 30), livrables='["Environnement POC", "Rapport de validation"]'),
    PhaseORM(id="PH-IC-003", project_id="PRJ-IC", name="Déploiement production",
             description="Migration complète, formation équipes, documentation ops",
             planned_jh=37.0, consumed_jh=8.0, status="open",
             closed_date=None, livrables='[]'),
    # PRJ-PCD — 3 phases
    PhaseORM(id="PH-PCD-001", project_id="PRJ-PCD", name="UX/UI Design",
             description="Wireframes, maquettes Figma, tests utilisateurs (5 sessions)",
             planned_jh=15.0, consumed_jh=15.0, status="closed",
             closed_date=date(2026, 4, 20), livrables='["Maquettes validées", "Design system"]'),
    PhaseORM(id="PH-PCD-002", project_id="PRJ-PCD", name="Développement frontend React",
             description="Implémentation composants, intégration API REST, tests E2E",
             planned_jh=42.0, consumed_jh=42.0, status="closed",
             closed_date=date(2026, 6, 16), livrables='["Application web", "Tests E2E"]'),
    PhaseORM(id="PH-PCD-003", project_id="PRJ-PCD", name="Recette & mise en production",
             description="Tests de recette client, correctifs, déploiement production",
             planned_jh=43.0, consumed_jh=0.0, status="open",
             closed_date=None, livrables='[]'),
]


def main() -> None:
    engine = build_engine(DB_URL)
    init_db(engine)
    sf = build_session_factory(engine)
    session = sf()

    try:
        inserted_projects = inserted_phases = 0

        for p in PROJECTS:
            existing = session.get(CharteProjetORM, p.id)
            if not existing:
                session.add(p)
                inserted_projects += 1

        for ph in PHASES:
            existing = session.get(PhaseORM, ph.id)
            if not existing:
                session.add(ph)
                inserted_phases += 1

        session.commit()
        print(f"Seeded {inserted_projects} projects, {inserted_phases} phases.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
