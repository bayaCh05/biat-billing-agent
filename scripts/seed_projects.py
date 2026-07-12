#!/usr/bin/env python3
"""Seed 3 demo projects + 9 phases into MongoDB (idempotent).

Usage:
    python scripts/seed_projects.py
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

# api.auth must be imported first (before src.storage.mongodb) — it's what
# loads .env (MONGODB_URI included), which mongodb.py reads as a module-level
# constant at import time.
import api.auth  # noqa: F401
from src.storage.mongodb import close_mongodb, init_beanie
from src.storage.sync_mongo_repository import save_charte_projet_sync, save_phase_sync

PROJECTS = [
    dict(
        id="CHR-2026-0001",
        project_id="PRJ-CBK",
        project_name="Migration Core Banking System",
        client="BIAT",
        valid_from=date(2026, 1, 5),
        valid_until=date(2026, 12, 31),
        budget_jh=120.0,
        taux_jh=850.0,
    ),
    dict(
        id="CHR-2026-0002",
        project_id="PRJ-IC",
        project_name="Infrastructure Cloud Hybride",
        client="BIAT",
        valid_from=date(2026, 2, 1),
        valid_until=date(2026, 9, 30),
        budget_jh=80.0,
        taux_jh=850.0,
    ),
    dict(
        id="CHR-2026-0003",
        project_id="PRJ-PCD",
        project_name="Portail Client Digital",
        client="BIAT",
        valid_from=date(2026, 3, 1),
        valid_until=date(2026, 11, 30),
        budget_jh=100.0,
        taux_jh=850.0,
    ),
]

PHASES = [
    # PRJ-CBK — 3 phases
    dict(id="PH-CBK-001", project_id="PRJ-CBK", name="Analyse & spécifications",
         description="Cadrage fonctionnel, recueil besoins, rédaction cahier des charges",
         planned_jh=20.0, consumed_jh=20.0, status="closed",
         closed_date=date(2026, 3, 31),
         livrables='["Cahier des charges", "Matrice des exigences"]'),
    dict(id="PH-CBK-002", project_id="PRJ-CBK", name="Architecture technique",
         description="Conception architecture cible, choix technologiques, prototypage",
         planned_jh=18.0, consumed_jh=18.0, status="closed",
         closed_date=date(2026, 5, 15), livrables='["Dossier d\'architecture", "POC validé"]'),
    dict(id="PH-CBK-003", project_id="PRJ-CBK", name="Développement & tests",
         description="Développement modules, tests unitaires et intégration",
         planned_jh=82.0, consumed_jh=24.0, status="open",
         closed_date=None, livrables='[]'),
    # PRJ-IC — 3 phases
    dict(id="PH-IC-001", project_id="PRJ-IC", name="Audit infrastructure existante",
         description="Inventaire, audit sécurité, identification dépendances",
         planned_jh=15.0, consumed_jh=15.0, status="closed",
         closed_date=date(2026, 3, 15), livrables='["Rapport d\'audit", "Cartographie SI"]'),
    dict(id="PH-IC-002", project_id="PRJ-IC", name="POC Cloud hybride",
         description="Mise en place environnement test, migration pilote 3 serveurs",
         planned_jh=28.0, consumed_jh=28.0, status="closed",
         closed_date=date(2026, 5, 30), livrables='["Environnement POC", "Rapport de validation"]'),
    dict(id="PH-IC-003", project_id="PRJ-IC", name="Déploiement production",
         description="Migration complète, formation équipes, documentation ops",
         planned_jh=37.0, consumed_jh=8.0, status="open",
         closed_date=None, livrables='[]'),
    # PRJ-PCD — 3 phases
    dict(id="PH-PCD-001", project_id="PRJ-PCD", name="UX/UI Design",
         description="Wireframes, maquettes Figma, tests utilisateurs (5 sessions)",
         planned_jh=15.0, consumed_jh=15.0, status="closed",
         closed_date=date(2026, 4, 20), livrables='["Maquettes validées", "Design system"]'),
    dict(id="PH-PCD-002", project_id="PRJ-PCD", name="Développement frontend React",
         description="Implémentation composants, intégration API REST, tests E2E",
         planned_jh=42.0, consumed_jh=42.0, status="closed",
         closed_date=date(2026, 6, 16), livrables='["Application web", "Tests E2E"]'),
    dict(id="PH-PCD-003", project_id="PRJ-PCD", name="Recette & mise en production",
         description="Tests de recette client, correctifs, déploiement production",
         planned_jh=43.0, consumed_jh=0.0, status="open",
         closed_date=None, livrables='[]'),
]


async def main() -> None:
    if not await init_beanie():
        print("MONGODB_URI non défini ou connexion impossible — abandon.")
        sys.exit(1)

    inserted_projects = sum(1 for p in PROJECTS if save_charte_projet_sync(**p))
    inserted_phases = sum(1 for ph in PHASES if save_phase_sync(**ph))

    print(f"Seeded {inserted_projects} projects, {inserted_phases} phases "
          f"({len(PROJECTS) - inserted_projects} projects and "
          f"{len(PHASES) - inserted_phases} phases already présents, ignorés).")

    await close_mongodb()


if __name__ == "__main__":
    asyncio.run(main())
