"""Seed demo risk data for the Risk Management module into MongoDB.

Usage:
    python scripts/seed_risks.py

Creates 14 example risks: 5 general risks (linked to projects and roadmap
items) plus 9 risks tied to the 3 real demo projects (PRJ-CBK, PRJ-IC,
PRJ-PCD) — merged from the former scripts/seed_risks_par_projet.py.
"""
from __future__ import annotations

import asyncio
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
from src.storage.sync_mongo_repository import _get_db, save_risque_sync

RISKS = [
    # ── Risques généraux ──────────────────────────────────────────────────────
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
        "projet_id": None,  # linked to a roadmap item below, if one exists
        "link_to_roadmap": True,
    },

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


async def main() -> None:
    if not await init_beanie():
        print("MONGODB_URI non défini ou connexion impossible — abandon.")
        sys.exit(1)

    feuille = _get_db()["feuilles_de_route"].find_one({})
    feuille_route_id = feuille["_id"] if feuille else None

    created = 0
    for r in RISKS:
        data = dict(r)
        link_to_roadmap = data.pop("link_to_roadmap", False)
        feuille_route_id_for_risk = feuille_route_id if link_to_roadmap else None

        ok = save_risque_sync(
            titre=data["titre"], description=data["description"],
            type_risque=data["type_risque"], probabilite=data["probabilite"],
            impact=data["impact"], statut=data["statut"],
            plan_mitigation=data["plan_mitigation"], responsable_id=data["responsable_id"],
            date_identification=data["date_identification"],
            date_echeance_mitigation=data["date_echeance_mitigation"],
            projet_id=data["projet_id"], created_by="admin@biat-it.tn",
            feuille_route_id=feuille_route_id_for_risk,
        )
        proj = data["projet_id"] or "transversal"
        if ok:
            created += 1
            print(f"  [{proj:14}] {data['titre'][:55]}")
        else:
            print(f"  (déjà présent) [{proj:14}] {data['titre'][:55]}")

    print(f"\n✓ {created} risques créés ({len(RISKS) - created} déjà présents, ignorés).")

    await close_mongodb()


if __name__ == "__main__":
    asyncio.run(main())
