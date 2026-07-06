"""Seed roadmap items (feuilles de route) across all 3 projects for 2026.

Covers all 4 quarters, all statuts, and varied priorities to test:
  - Gantt bar rendering (T1–T4 positions)
  - Late / at-risk / on-time detection
  - Project filter
  - Risk side-panel (the 3 items that already had feuille_route_id risks)

Usage:
    python scripts/seed_roadmap.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.db import build_engine, build_session_factory, init_db
from src.storage.orm_models_roadmap import FeuilleDeRouteORM

# Today is 2026-07-06

ITEMS = [
    # ── PRJ-CBK : Migration Core Banking System ──────────────────────────────
    {
        "titre": "Analyse des systèmes Core Banking existants",
        "description": "Cartographie complète des flux, schémas BD, API et dépendances du Core Banking v1.",
        "date_debut": date(2026, 1, 6),
        "date_fin":   date(2026, 2, 28),
        "statut":     "TERMINE",
        "priorite":   "HAUTE",
        "projet_id":  "PRJ-CBK",
        "responsable_id": "chef@biat-it.tn",
    },
    {
        "titre": "Design de l'architecture cible v2",
        "description": "Spécifications techniques, choix technologiques, couche d'abstraction API.",
        "date_debut": date(2026, 3, 2),
        "date_fin":   date(2026, 5, 30),   # passé → EN_COURS = late
        "statut":     "EN_COURS",
        "priorite":   "HAUTE",
        "projet_id":  "PRJ-CBK",
        "responsable_id": "chef@biat-it.tn",
    },
    {
        "titre": "Développement connecteurs API Core Banking",
        "description": "Implémentation des adaptateurs REST/SOAP pour les modules Crédit, DAV et Épargne.",
        "date_debut": date(2026, 6, 1),
        "date_fin":   date(2026, 8, 31),
        "statut":     "EN_COURS",
        "priorite":   "HAUTE",
        "projet_id":  "PRJ-CBK",
        "responsable_id": "chef@biat-it.tn",
    },
    {
        "titre": "Tests de régression et validation recette",
        "description": "Campagne de tests sur environnement de recette — 250 cas de test planifiés.",
        "date_debut": date(2026, 9, 1),
        "date_fin":   date(2026, 10, 15),
        "statut":     "PLANIFIE",
        "priorite":   "HAUTE",
        "projet_id":  "PRJ-CBK",
        "responsable_id": "chef@biat-it.tn",
    },
    {
        "titre": "Go-live Core Banking v2",
        "description": "Bascule de production planifiée hors fin de mois avec rollback automatisé.",
        "date_debut": date(2026, 11, 2),
        "date_fin":   date(2026, 11, 30),
        "statut":     "PLANIFIE",
        "priorite":   "HAUTE",
        "projet_id":  "PRJ-CBK",
        "responsable_id": "directeur@biat-it.tn",
    },

    # ── PRJ-IC : Infrastructure Cloud Hybride ────────────────────────────────
    # (3 items already exist; adding complementary milestones)
    {
        "titre": "Sélection fournisseur cloud et négociation contrat",
        "description": "Appel d'offres, évaluation technique et commerciale, signature SLA.",
        "date_debut": date(2026, 1, 5),
        "date_fin":   date(2026, 2, 15),
        "statut":     "TERMINE",
        "priorite":   "HAUTE",
        "projet_id":  "PRJ-IC",
        "responsable_id": "directeur@biat-it.tn",
    },
    {
        "titre": "Déploiement réseau SD-WAN inter-sites",
        "description": "Installation et configuration SD-WAN entre les 3 datacenters BIAT.",
        "date_debut": date(2026, 4, 1),
        "date_fin":   date(2026, 6, 15),   # passé → EN_COURS = late
        "statut":     "EN_COURS",
        "priorite":   "MOYENNE",
        "projet_id":  "PRJ-IC",
        "responsable_id": "chef@biat-it.tn",
    },
    {
        "titre": "Mise en place monitoring et alerting cloud",
        "description": "Déploiement Prometheus/Grafana, définition des seuils d'alerte et runbooks.",
        "date_debut": date(2026, 8, 1),
        "date_fin":   date(2026, 9, 30),
        "statut":     "PLANIFIE",
        "priorite":   "MOYENNE",
        "projet_id":  "PRJ-IC",
        "responsable_id": "chef@biat-it.tn",
    },
    {
        "titre": "Bascule définitive et désaffectation ancien datacenter",
        "description": "Migration finale des charges restantes et arrêt des serveurs on-premise.",
        "date_debut": date(2026, 11, 1),
        "date_fin":   date(2026, 12, 31),
        "statut":     "PLANIFIE",
        "priorite":   "HAUTE",
        "projet_id":  "PRJ-IC",
        "responsable_id": "directeur@biat-it.tn",
    },

    # ── PRJ-PCD : Portail Client Digital ─────────────────────────────────────
    # (1 item already exists: Portail Clients — Design UX, TERMINE)
    {
        "titre": "Analyse des besoins et parcours utilisateurs",
        "description": "Ateliers avec 12 agences pilotes, persona, carte de parcours client.",
        "date_debut": date(2026, 1, 5),
        "date_fin":   date(2026, 2, 20),
        "statut":     "TERMINE",
        "priorite":   "HAUTE",
        "projet_id":  "PRJ-PCD",
        "responsable_id": "chef@biat-it.tn",
    },
    {
        "titre": "Développement module authentification SSO",
        "description": "Intégration OIDC avec le fournisseur SSO — en retard suite à délai prestataire.",
        "date_debut": date(2026, 4, 1),
        "date_fin":   date(2026, 6, 30),   # passé → EN_COURS = late
        "statut":     "EN_COURS",
        "priorite":   "HAUTE",
        "projet_id":  "PRJ-PCD",
        "responsable_id": "chef@biat-it.tn",
    },
    {
        "titre": "Développement tableau de bord client",
        "description": "Solde, mouvements, virements, simulation crédit — interface responsive.",
        "date_debut": date(2026, 7, 1),
        "date_fin":   date(2026, 9, 15),
        "statut":     "PLANIFIE",
        "priorite":   "HAUTE",
        "projet_id":  "PRJ-PCD",
        "responsable_id": "chef@biat-it.tn",
    },
    {
        "titre": "Tests pilotes — 3 agences BIAT",
        "description": "Déploiement limité à Tunis Centre, Lac 1 et Sfax. Recueil feedback.",
        "date_debut": date(2026, 9, 16),
        "date_fin":   date(2026, 10, 31),
        "statut":     "PLANIFIE",
        "priorite":   "MOYENNE",
        "projet_id":  "PRJ-PCD",
        "responsable_id": "directeur@biat-it.tn",
    },
    {
        "titre": "Déploiement national portail client",
        "description": "Ouverture à tous les clients BIAT avec support 24/7 et FAQ embarquée.",
        "date_debut": date(2026, 11, 15),
        "date_fin":   date(2026, 12, 15),
        "statut":     "PLANIFIE",
        "priorite":   "HAUTE",
        "projet_id":  "PRJ-PCD",
        "responsable_id": "directeur@biat-it.tn",
    },

    # ── Transversal (no project) ──────────────────────────────────────────────
    {
        "titre": "Audit sécurité SI — périmètre complet BIAT IT",
        "description": "Pentest externe + revue architecture — obligatoire avant tout go-live.",
        "date_debut": date(2026, 7, 13),
        "date_fin":   date(2026, 7, 12),   # 1 day — used for at-risk test (within 7 days from today 07-06)
        "statut":     "PLANIFIE",
        "priorite":   "HAUTE",
        "projet_id":  None,
        "responsable_id": "directeur@biat-it.tn",
    },
    {
        "titre": "Formation DevOps — équipes techniques",
        "description": "3 jours de formation CI/CD, conteneurs et IaC pour 8 ingénieurs.",
        "date_debut": date(2026, 3, 16),
        "date_fin":   date(2026, 3, 20),
        "statut":     "TERMINE",
        "priorite":   "BASSE",
        "projet_id":  None,
        "responsable_id": "chef@biat-it.tn",
    },
]


def main() -> None:
    engine = build_engine("sqlite:///./data/invoices.db")
    init_db(engine)
    sf = build_session_factory(engine)

    today = date(2026, 7, 6)

    with sf() as session:
        for item in ITEMS:
            days_left = (item["date_fin"] - today).days
            is_late = days_left < 0 and item["statut"] not in ("TERMINE", "ANNULE")
            flag = "⚠ LATE" if is_late else ("✓" if item["statut"] == "TERMINE" else "→")
            orm = FeuilleDeRouteORM(
                titre=item["titre"],
                description=item["description"],
                date_debut=item["date_debut"],
                date_fin=item["date_fin"],
                statut=item["statut"],
                priorite=item["priorite"],
                projet_id=item.get("projet_id"),
                responsable_id=item.get("responsable_id"),
                annee=2026,
            )
            session.add(orm)
            proj = item.get("projet_id") or "transversal"
            print(f"  {flag} [{proj:10}] {item['titre'][:55]}")

        session.commit()
        print(f"\n✓ {len(ITEMS)} jalons créés.")


if __name__ == "__main__":
    main()
