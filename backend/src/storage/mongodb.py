"""Connexion MongoDB et initialisation Beanie.

Point d'entrée unique pour la couche de persistance MongoDB.
Coexiste avec SQLAlchemy/SQLite durant la migration — si MONGODB_URI
n'est pas défini, l'application continue en mode SQLite uniquement.

Utilisation dans le lifespan FastAPI (api/main.py) :

    from src.storage.mongodb import init_beanie, close_mongodb
    await init_beanie()          # au démarrage
    ...
    await close_mongodb()        # à l'arrêt

Variables d'environnement :
    MONGODB_URI  — URI de connexion (ex: mongodb://localhost:27017)
                   Si absent → mode SQLite uniquement, aucun crash.
    MONGODB_DB   — Nom de la base de données (défaut: biat_billing)
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

MONGODB_URI: str = os.getenv("MONGODB_URI", "")
MONGODB_DB:  str = os.getenv("MONGODB_DB", "biat_billing")

# Client Motor conservé pour pouvoir fermer proprement la connexion à l'arrêt.
_motor_client = None


async def init_beanie(document_models: list | None = None) -> bool:
    """Initialise Motor + Beanie au démarrage de l'application.

    Retourne True si la connexion a réussi.
    Retourne False (sans lever d'exception) si MONGODB_URI est absent
    ou si la connexion échoue — l'application reste en mode SQLite.

    Args:
        document_models: liste des classes Document Beanie à enregistrer.
            None → utilise _all_document_models() (liste complète).
            []   → valide pour les tests sans modèles.
    """
    global _motor_client

    if not MONGODB_URI:
        logger.info(
            "mongodb: MONGODB_URI non défini — mode SQLite uniquement."
        )
        return False

    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        import beanie

        _motor_client = AsyncIOMotorClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=5_000,
        )
        # Vérification rapide que le serveur répond avant d'aller plus loin.
        await _motor_client.admin.command("ping")

        db = _motor_client[MONGODB_DB]
        models = document_models if document_models is not None else _all_document_models()

        await beanie.init_beanie(database=db, document_models=models)
        logger.info(
            "mongodb: connecté — base=%s documents=%d",
            MONGODB_DB, len(models),
        )
        return True

    except Exception as exc:
        logger.error("mongodb: échec de connexion — %s", exc)
        _motor_client = None
        return False


async def close_mongodb() -> None:
    """Ferme proprement le client Motor (appelé à l'arrêt de l'application)."""
    global _motor_client
    if _motor_client is not None:
        _motor_client.close()
        _motor_client = None
        logger.info("mongodb: connexion fermée.")


def _all_document_models() -> list:
    """Liste complète de tous les Documents Beanie de l'application (Phase 2 terminée)."""
    from src.storage.documents.user                    import UserDocument
    from src.storage.documents.audit_log               import AuditLogDocument
    from src.storage.documents.revoked_token           import RevokedTokenDocument
    from src.storage.documents.active_token            import ActiveTokenDocument
    from src.storage.documents.invoice                 import InvoiceDocument
    from src.storage.documents.payment                 import PaymentDocument
    from src.storage.documents.journal_entry           import JournalEntryDocument
    from src.storage.documents.client_invoice          import ClientInvoiceDocument
    from src.storage.documents.asset                   import AssetDocument
    from src.storage.documents.budget_plan             import BudgetPlanDocument
    from src.storage.documents.payment_installment     import PaymentInstallmentDocument
    from src.storage.documents.classification_feedback import ClassificationFeedbackDocument
    from src.storage.documents.charte_projet           import CharteProjetDocument
    from src.storage.documents.phase                   import PhaseDocument
    from src.storage.documents.fiche_mensuelle         import FicheMensuelleDocument
    from src.storage.documents.feuille_de_route        import FeuilleDeRouteDocument
    from src.storage.documents.ligne_budget            import LigneBudgetDocument
    from src.storage.documents.livrable                import LivrableDocument
    from src.storage.documents.risque                  import RisqueDocument
    from src.storage.documents.notification            import NotificationDocument
    from src.storage.documents.password_verification   import PasswordVerificationDocument
    from src.storage.documents.audit_snapshot           import AuditSnapshotDocument

    return [
        UserDocument,
        AuditLogDocument,
        RevokedTokenDocument,
        ActiveTokenDocument,
        InvoiceDocument,
        PaymentDocument,
        JournalEntryDocument,
        ClientInvoiceDocument,
        AssetDocument,
        BudgetPlanDocument,
        PaymentInstallmentDocument,
        ClassificationFeedbackDocument,
        CharteProjetDocument,
        PhaseDocument,
        FicheMensuelleDocument,
        FeuilleDeRouteDocument,
        LigneBudgetDocument,
        LivrableDocument,
        RisqueDocument,
        NotificationDocument,
        PasswordVerificationDocument,
        AuditSnapshotDocument,
    ]
