"""AI endpoints — health summary, risk scan, mitigation, consistency check, activity log."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import require_role
from api.deps import get_components

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["analytics"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class MitigationRequest(BaseModel):
    titre: str
    type_risque: str
    probabilite: str
    impact: str


class ClassificationCorrectionRequest(BaseModel):
    cost_catalog_id: str
    accounting_compte: str
    invoice_text: str = ""


# ── Health summary ────────────────────────────────────────────────────────────

@router.get(
    "/health-summary",
    summary="Résumé IA de l'état de santé financier",
    description=(
        "Génère un résumé exécutif en français (3 phrases max) basé sur les KPIs "
        "en temps réel : factures, budget, roadmap, risques, paiements. "
        "Requiert Ollama actif ; retourne un message dégradé sinon."
    ),
)
def get_health_summary(
    _user=Depends(require_role("Comptable", "Chef de Projet", "Direction", "Admin")),
):
    from src.ai_agents.insight_agent import InsightAgent
    from src.ai_agents.ollama_client import OllamaClient
    agent = InsightAgent()
    result = agent.run({"task": "health_summary"})
    if not result.success:
        raise HTTPException(500, detail=result.error or "Échec de la génération du résumé.")
    return {
        **result.output,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ollama_available": OllamaClient.get().is_available(),
    }


# ── Risk scan ─────────────────────────────────────────────────────────────────

@router.post(
    "/scan-roadmap-risks",
    summary="Scan IA des jalons en retard → création de risques",
    description=(
        "Analyse la feuille de route et crée automatiquement des risques "
        "pour chaque jalon en retard. Évite les doublons si un risque IA "
        "existe déjà pour le même jalon. Admin uniquement."
    ),
)
def scan_roadmap_risks(
    _user=Depends(require_role("Admin")),
):
    from src.ai_agents.risk_agent import RiskAgent
    result = RiskAgent().run({"task": "scan_roadmap"})
    if not result.success:
        raise HTTPException(500, detail=result.error or "Scan failed")
    return result.output


@router.post(
    "/scan-item-risk/{item_id}",
    summary="Créer risque IA pour un jalon spécifique en retard",
    description=(
        "Génère un risque de type DELAI via l'IA pour le jalon identifié. "
        "Accessible aux Chef de Projet et Admin. "
        "Évite les doublons si un risque IA existe déjà pour ce jalon."
    ),
)
def scan_item_risk(
    item_id: str,
    _user=Depends(require_role("Chef de Projet", "Admin")),
):
    from src.ai_agents.risk_agent import RiskAgent
    result = RiskAgent().run({"task": "scan_roadmap", "item_id": item_id})
    if not result.success:
        raise HTTPException(500, detail=result.error or "Scan failed")
    return result.output


# ── Mitigation suggestion ─────────────────────────────────────────────────────

@router.post(
    "/suggest-mitigation",
    summary="Générer un plan de mitigation IA pour un risque",
    description=(
        "Produit 3 actions de mitigation concrètes en français pour le risque décrit. "
        "Utilise Ollama local — retourne un plan de secours si Ollama est indisponible."
    ),
)
def suggest_mitigation(
    body: MitigationRequest,
    _user=Depends(require_role("Chef de Projet", "Admin")),
):
    from src.ai_agents.risk_agent import RiskAgent
    result = RiskAgent().run({
        "task": "draft_mitigation",
        "titre": body.titre,
        "type_risque": body.type_risque,
        "probabilite": body.probabilite,
        "impact": body.impact,
    })
    if not result.success:
        raise HTTPException(500, detail=result.error or "Échec de la génération du plan de mitigation.")
    return {"suggestion": result.output.get("suggestion", ""), "duration_ms": result.duration_ms}


# ── Accounting consistency check ──────────────────────────────────────────────

@router.post(
    "/accounting-check",
    summary="Audit de cohérence des écritures comptables",
    description=(
        "Vérifie que toutes les écritures sont équilibrées (débit = crédit ± 0,005 TND). "
        "Admin uniquement."
    ),
)
def accounting_check(
    _user=Depends(require_role("Admin")),
):
    components = get_components()
    try:
        from src.ai_agents.accounting_agent import AccountingAgent
        agent = AccountingAgent(components.entry_generator, cost_catalog=components.cost_catalog)
        return agent.check_consistency()
    finally:
        components.close()


# ── Retrain ML model ──────────────────────────────────────────────────────────

@router.post(
    "/retrain",
    summary="Relancer l'entraînement du modèle ML de classification",
    description=(
        "Réentraîne le modèle TF-IDF + LogisticRegression sur les factures "
        "validées + corrections manuelles. Admin uniquement."
    ),
)
def retrain_model(
    _user=Depends(require_role("Admin")),
):
    components = get_components()
    try:
        try:
            # Mongo, not components.repository (SQLAlchemy) — invoices uploaded
            # through the real API path only ever land in Mongo; see
            # scheduler.py::_job_retrain_classifier for the same fix.
            from src.storage.sync_mongo_repository import SyncMongoInvoiceRepository
            components.coder.ml_classifier.retrain_from_repo(SyncMongoInvoiceRepository())
            return {"status": "ok", "message": "Modèle ML réentraîné avec succès."}
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("retrain_model_error: %s", exc)
            raise HTTPException(500, detail="Erreur interne lors du réentraînement du modèle ML.")
    finally:
        components.close()


# ── AI activity log ───────────────────────────────────────────────────────────

@router.get(
    "/activity",
    summary="Journal d'activité IA",
    description=(
        "Retourne les statistiques Ollama (appels, taux de succès, durée moyenne) "
        "ainsi que les dernières entrées de log pour le monitoring IA. Admin uniquement."
    ),
)
def get_ai_activity(
    _user=Depends(require_role("Admin")),
):
    from src.ai_agents.ollama_client import OllamaClient
    client = OllamaClient.get()
    stats = client.get_stats()
    return {
        "ollama_stats": stats,
        "ollama_available": client.is_available(),
        "model": __import__("os").getenv("OLLAMA_MODEL", "qwen2.5:3b"),
    }


# ── Classification correction feedback ────────────────────────────────────────

@router.patch(
    "/invoices/{invoice_id}/classification",
    summary="Corriger la classification d'une facture",
    description=(
        "Enregistre une correction manuelle de classification. "
        "La correction est sauvegardée dans classification_feedback. "
        "Si 10+ corrections s'accumulent, le modèle ML est relancé en arrière-plan."
    ),
)
def correct_classification(
    invoice_id: str,
    body: ClassificationCorrectionRequest,
    user=Depends(require_role("Comptable", "Admin")),
):
    from uuid import UUID

    from src.storage.sync_mongo_repository import (
        SyncMongoInvoiceRepository, count_classification_feedback_sync,
        save_classification_feedback_sync,
    )

    repo = SyncMongoInvoiceRepository()
    try:
        uid = UUID(invoice_id)
    except ValueError:
        raise HTTPException(400, "Invalid UUID")

    inv = repo.get_by_id(uid)
    if not inv:
        raise HTTPException(404, "Invoice not found")

    original_compte = inv.accounting_compte or ""
    save_classification_feedback_sync(
        invoice_id=invoice_id,
        original_compte=original_compte,
        corrected_compte=body.accounting_compte,
        original_catalog_id=inv.cost_catalog_id,
        corrected_catalog_id=body.cost_catalog_id,
        invoice_text=body.invoice_text or inv.raw_extracted_text or "",
        corrected_by=getattr(user, "email", str(user)),
    )

    # Apply correction to invoice
    inv.accounting_compte = body.accounting_compte
    inv.cost_catalog_id = body.cost_catalog_id
    repo.save(inv)

    # Count feedback and trigger retrain if threshold reached
    count = count_classification_feedback_sync()
    retrain_triggered = False
    if count >= 10 and count % 10 == 0:
        try:
            components = get_components()
            try:
                components.coder.ml_classifier.retrain_from_repo(SyncMongoInvoiceRepository())
                retrain_triggered = True
                logger.info("ml_retrain_triggered feedback_count=%d", count)
            finally:
                components.close()
        except Exception as exc:
            logger.warning("ml_retrain_error: %s", exc)

    return {
        "invoice_id": invoice_id,
        "corrected_compte": body.accounting_compte,
        "feedback_count": count,
        "retrain_triggered": retrain_triggered,
    }
