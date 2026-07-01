"""Seed demo risk data for the Risk Management module.

Usage:
    python scripts/seed_risks.py

Creates 5 example risks linked to projects and roadmap items.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.db import build_engine, build_session_factory, init_db
from src.storage.orm_models_extra import RisqueORM, FeuilleDeRouteORM
from src.services.risk_service import calculate_criticite

RISKS = [
    {
        "titre": "Retard de livraison du module OCR",
        "description": "Le prestataire OCR a signalé un délai de 3 semaines sur le module d'extraction.",
        "type_risque": "DELAI",
        "probabilite": "ELEVEE",
        "impact": "ELEVE",
        "statut": "EN_TRAITEMENT",
        "plan_mitigation": "Identifier un prestataire de secours. Activer le fallback Tesseract en production.",
        "responsable_id": "chef@biat-it.tn",
        "date_identification": date(2026, 4, 10),
        "date_echeance_mitigation": date(2026, 5, 15),
        "projet_id": "proj-ocr-2026",
    },
    {
        "titre": "Dépassement budget infrastructure cloud",
        "description": "Les coûts d'hébergement ont été sous-estimés de 30% dans le plan initial.",
        "type_risque": "BUDGET",
        "probabilite": "MOYENNE",
        "impact": "CRITIQUE",
        "statut": "EN_SURVEILLANCE",
        "plan_mitigation": "Renégocier le contrat avec le fournisseur. Optimiser les instances sous-utilisées.",
        "responsable_id": "comptable@biat-it.tn",
        "date_identification": date(2026, 3, 20),
        "date_echeance_mitigation": date(2026, 6, 30),
        "projet_id": "proj-infra-2026",
    },
    {
        "titre": "Incompatibilité API bancaire BIAT Core",
        "description": "L'API Core Banking v2 introduit des changements incompatibles avec le module de facturation.",
        "type_risque": "TECHNIQUE",
        "probabilite": "MOYENNE",
        "impact": "CRITIQUE",
        "statut": "IDENTIFIE",
        "plan_mitigation": "Mettre en place une couche d'abstraction (adapter). Tester en environnement de recette.",
        "responsable_id": "chef@biat-it.tn",
        "date_identification": date(2026, 5, 5),
        "date_echeance_mitigation": date(2026, 7, 1),
        "projet_id": "proj-billing-2026",
    },
    {
        "titre": "Manque de ressources humaines qualifiées MLOps",
        "description": "Les profils MLOps nécessaires au déploiement du moteur IA ne sont pas disponibles en interne.",
        "type_risque": "RESSOURCE",
        "probabilite": "FAIBLE",
        "impact": "ELEVE",
        "statut": "MAITRISE",
        "plan_mitigation": "Recrutement de 2 profils MLOps prévu Q3. Formation interne validée par DRH.",
        "responsable_id": "directeur@biat-it.tn",
        "date_identification": date(2026, 2, 15),
        "date_echeance_mitigation": date(2026, 9, 1),
        "projet_id": "proj-ia-2026",
    },
    {
        "titre": "Risque réglementaire — conservation des données",
        "description": "Nouvelle directive BCT sur la durée de rétention des logs — impact sur l'architecture de stockage.",
        "type_risque": "REGLEMENTAIRE",
        "probabilite": "FAIBLE",
        "impact": "CRITIQUE",
        "statut": "EN_SURVEILLANCE",
        "plan_mitigation": "Consultation avec le département juridique. Révision de la politique de rétention.",
        "responsable_id": "directeur@biat-it.tn",
        "date_identification": date(2026, 6, 1),
        "date_echeance_mitigation": date(2026, 12, 31),
        "projet_id": None,  # will be linked to roadmap item
    },
]


def main() -> None:
    engine = build_engine("sqlite:///./data/invoices.db")
    init_db(engine)
    sf = build_session_factory(engine)

    with sf() as session:
        # Try to find a roadmap item for the last risk
        feuille = session.query(FeuilleDeRouteORM).first()

        for i, r in enumerate(RISKS):
            risk_data = dict(r)
            risk_data["niveau_criticite"] = calculate_criticite(r["probabilite"], r["impact"])
            risk_data["created_by"] = "admin@biat-it.tn"
            risk_data["created_at"] = datetime.now(timezone.utc)
            risk_data["updated_at"] = datetime.now(timezone.utc)

            # Link last risk to roadmap item if available
            if i == len(RISKS) - 1 and feuille:
                risk_data["feuille_route_id"] = feuille.id
                risk_data["projet_id"] = None

            orm = RisqueORM(**risk_data)
            session.add(orm)
            print(f"  ✓ {r['titre'][:60]} — criticité: {risk_data['niveau_criticite']}")

        session.commit()
        print(f"\n✓ {len(RISKS)} risques créés avec succès.")


if __name__ == "__main__":
    main()
