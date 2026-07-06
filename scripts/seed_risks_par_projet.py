"""Seed test risks linked to real projects (PRJ-CBK, PRJ-IC, PRJ-PCD).

Usage:
    python scripts/seed_risks_par_projet.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.db import build_engine, build_session_factory, init_db
from src.storage.orm_models_roadmap import RisqueORM
from src.services.risk_service import calculate_criticite

RISKS = [
    # ── PRJ-CBK : Migration Core Banking System ──────────────────────────────
    {
        "titre": "Incompatibilité schéma BD Core Banking v2",
        "description": (
            "La migration vers Core Banking v2 expose des colonnes renommées et des "
            "contraintes FK incompatibles avec l'ORM actuel — 14 tables affectées."
        ),
        "type_risque": "TECHNIQUE",
        "probabilite": "ELEVEE",
        "impact": "CRITIQUE",
        "statut": "EN_TRAITEMENT",
        "plan_mitigation": (
            "Générer un rapport de diff de schéma. Rédiger des scripts Alembic de "
            "rétrocompatibilité. Tester en environnement de recette avant la mise en prod."
        ),
        "responsable_id": "chef@biat-it.tn",
        "date_identification": date(2026, 5, 12),
        "date_echeance_mitigation": date(2026, 7, 20),
        "projet_id": "PRJ-CBK",
    },
    {
        "titre": "Risque de perte de données lors de la bascule",
        "description": (
            "La fenêtre de bascule de 4 h prévue est insuffisante pour les volumes "
            "de transactions de fin de mois — risque de corruption partielle."
        ),
        "type_risque": "TECHNIQUE",
        "probabilite": "MOYENNE",
        "impact": "CRITIQUE",
        "statut": "EN_SURVEILLANCE",
        "plan_mitigation": (
            "Planifier la bascule un week-end hors fin de mois. Mettre en place un "
            "snapshot DB avant bascule et un rollback automatisé testé."
        ),
        "responsable_id": "chef@biat-it.tn",
        "date_identification": date(2026, 4, 28),
        "date_echeance_mitigation": date(2026, 8, 1),
        "projet_id": "PRJ-CBK",
    },
    {
        "titre": "Dépassement du budget licences Core Banking",
        "description": (
            "Le fournisseur a revu son tarif de licences à la hausse de 22 % "
            "après signature — surcoût estimé à 85 kTND."
        ),
        "type_risque": "BUDGET",
        "probabilite": "ELEVEE",
        "impact": "ELEVE",
        "statut": "IDENTIFIE",
        "plan_mitigation": (
            "Ouvrir une négociation avec le fournisseur pour obtenir un tarif "
            "contractuel. En parallèle, identifier des postes de compensation budgétaire."
        ),
        "responsable_id": "directeur@biat-it.tn",
        "date_identification": date(2026, 6, 3),
        "date_echeance_mitigation": date(2026, 7, 31),
        "projet_id": "PRJ-CBK",
    },

    # ── PRJ-IC : Infrastructure Cloud Hybride ────────────────────────────────
    {
        "titre": "Latence réseau inter-datacenter supérieure au SLA",
        "description": (
            "Les tests de charge montrent une latence de 38 ms entre les nœuds "
            "privé/public, alors que le SLA exige < 20 ms pour les API critiques."
        ),
        "type_risque": "TECHNIQUE",
        "probabilite": "ELEVEE",
        "impact": "ELEVE",
        "statut": "EN_TRAITEMENT",
        "plan_mitigation": (
            "Déployer un cache Redis distribué pour les appels répétitifs. "
            "Revoir le routage BGP avec l'opérateur réseau. Réévaluer le SLA si nécessaire."
        ),
        "responsable_id": "chef@biat-it.tn",
        "date_identification": date(2026, 5, 20),
        "date_echeance_mitigation": date(2026, 7, 15),
        "projet_id": "PRJ-IC",
    },
    {
        "titre": "Dépassement budgétaire hébergement cloud",
        "description": (
            "La consommation réelle des instances compute est 31 % au-dessus du plan "
            "initial — les environnements de test n'ont pas été éteints hors heures ouvrées."
        ),
        "type_risque": "BUDGET",
        "probabilite": "MOYENNE",
        "impact": "CRITIQUE",
        "statut": "EN_SURVEILLANCE",
        "plan_mitigation": (
            "Mettre en place une politique d'auto-stop des instances de test la nuit "
            "et le week-end. Activer les alertes budgétaires à 80 % de consommation mensuelle."
        ),
        "responsable_id": "comptable@biat-it.tn",
        "date_identification": date(2026, 4, 15),
        "date_echeance_mitigation": date(2026, 6, 30),
        "projet_id": "PRJ-IC",
    },
    {
        "titre": "Non-conformité stockage données sensibles BCT",
        "description": (
            "La directive BCT 2026-04 impose que les données client restent sur sol "
            "tunisien — le bucket S3 configuré est hébergé dans la région eu-west-1."
        ),
        "type_risque": "REGLEMENTAIRE",
        "probabilite": "FAIBLE",
        "impact": "CRITIQUE",
        "statut": "IDENTIFIE",
        "plan_mitigation": (
            "Migrer les buckets vers une région locale ou un stockage on-premise. "
            "Obtenir la validation écrite du département juridique avant la mise en prod."
        ),
        "responsable_id": "directeur@biat-it.tn",
        "date_identification": date(2026, 6, 10),
        "date_echeance_mitigation": date(2026, 9, 30),
        "projet_id": "PRJ-IC",
    },

    # ── PRJ-PCD : Portail Client Digital ────────────────────────────────────
    {
        "titre": "Retard de livraison du module authentification SSO",
        "description": (
            "Le prestataire intégrateur SSO accuse un retard de 3 semaines "
            "sur l'implémentation OIDC — la date de go-live est menacée."
        ),
        "type_risque": "DELAI",
        "probabilite": "ELEVEE",
        "impact": "ELEVE",
        "statut": "EN_TRAITEMENT",
        "plan_mitigation": (
            "Activer un mécanisme d'authentification de secours (username/password + OTP). "
            "Renégocier les pénalités de retard avec le prestataire."
        ),
        "responsable_id": "chef@biat-it.tn",
        "date_identification": date(2026, 5, 30),
        "date_echeance_mitigation": date(2026, 7, 10),
        "projet_id": "PRJ-PCD",
    },
    {
        "titre": "Faible adoption utilisateurs — résistance au changement",
        "description": (
            "Les tests pilotes montrent un taux d'adoption de 34 % — "
            "les agents préfèrent les canaux existants (email/téléphone)."
        ),
        "type_risque": "RESSOURCE",
        "probabilite": "MOYENNE",
        "impact": "ELEVE",
        "statut": "EN_SURVEILLANCE",
        "plan_mitigation": (
            "Organiser 3 sessions de formation in-situ avant le déploiement. "
            "Désigner des ambassadeurs digitaux par direction. Mettre en place un "
            "tableau de bord de suivi d'adoption hebdomadaire."
        ),
        "responsable_id": "directeur@biat-it.tn",
        "date_identification": date(2026, 5, 5),
        "date_echeance_mitigation": date(2026, 8, 31),
        "projet_id": "PRJ-PCD",
    },
    {
        "titre": "Vulnérabilité XSS dans le formulaire de contact",
        "description": (
            "Un audit de sécurité a détecté une faille XSS réfléchi sur le champ "
            "commentaire du formulaire — CVSS score 7.2."
        ),
        "type_risque": "TECHNIQUE",
        "probabilite": "FAIBLE",
        "impact": "CRITIQUE",
        "statut": "MAITRISE",
        "plan_mitigation": (
            "Appliquer un encodage HTML systématique côté serveur. "
            "Activer la Content Security Policy. Audit de sécurité complet prévu Q3."
        ),
        "responsable_id": "chef@biat-it.tn",
        "date_identification": date(2026, 6, 18),
        "date_echeance_mitigation": date(2026, 6, 25),
        "projet_id": "PRJ-PCD",
    },
]


def main() -> None:
    engine = build_engine("sqlite:///./data/invoices.db")
    init_db(engine)
    sf = build_session_factory(engine)

    with sf() as session:
        for r in RISKS:
            risk_data = dict(r)
            risk_data["niveau_criticite"] = calculate_criticite(r["probabilite"], r["impact"])
            risk_data["created_by"] = "admin@biat-it.tn"
            risk_data["created_at"] = datetime.now(timezone.utc)
            risk_data["updated_at"] = datetime.now(timezone.utc)

            orm = RisqueORM(**risk_data)
            session.add(orm)
            crit = risk_data["niveau_criticite"]
            print(f"  [{r['projet_id']}] {r['titre'][:55]} — {crit}")

        session.commit()
        print(f"\n✓ {len(RISKS)} risques créés (3 par projet).")


if __name__ == "__main__":
    main()
