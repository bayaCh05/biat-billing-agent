"""Rapports d'audit périodiques (Audit Agent) — liste, détail, déclenchement
manuel. Lit uniquement des AuditSnapshotDocument déjà persistés (ou en
déclenche un nouveau via AuditAgent) — aucune logique métier ici.

Préfixe /audit-reports délibérément distinct de /audit (api/routers/audit.py
— intégrité HMAC des logs) pour éviter toute confusion entre les deux
domaines, voir CLAUDE.md "Audit Agent".
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audit-reports", tags=["audit-reports"])

_VALID_GRANULARITIES = {"DAILY", "WEEKLY", "MONTHLY"}
_VIEW = Depends(require_role("Chef de Projet", "Admin", "Direction", "Comptable"))
_RUN = Depends(require_role("Admin"))


class RunAuditReportRequest(BaseModel):
    granularity: str = "DAILY"


def _check_granularity(granularity: str) -> None:
    if granularity not in _VALID_GRANULARITIES:
        raise HTTPException(
            400, detail=f"granularity doit être l'une de {sorted(_VALID_GRANULARITIES)}"
        )


def _to_summary(doc: dict) -> dict:
    alerts = doc.get("alerts") or []
    return {
        "id": doc["_id"],
        "granularity": doc["granularity"],
        "period_start": doc["period_start"],
        "period_end": doc["period_end"],
        "generated_at": doc["generated_at"],
        "status": doc["status"],
        "alert_count": len(alerts),
        "critical_count": sum(1 for a in alerts if a.get("severity") == "CRITICAL"),
    }


@router.get(
    "",
    summary="Liste des rapports d'audit",
    description="Rapports les plus récents d'abord. Filtrable par granularité.",
)
def list_audit_reports(
    granularity: str | None = Query(None, description="DAILY | WEEKLY | MONTHLY"),
    limit: int = Query(20, ge=1, le=100),
    skip: int = Query(0, ge=0),
    _user=_VIEW,
):
    if granularity is not None:
        _check_granularity(granularity)

    from src.storage.sync_mongo_repository import (
        count_audit_snapshots_sync, list_audit_snapshots_sync,
    )

    docs = list_audit_snapshots_sync(granularity=granularity, limit=limit, skip=skip)
    total = count_audit_snapshots_sync(granularity=granularity)
    return {"total": total, "items": [_to_summary(d) for d in docs]}


@router.get(
    "/{snapshot_id}",
    summary="Détail complet d'un rapport d'audit",
    description=(
        "Métriques par domaine, tendance, rapprochement transversal, alertes, "
        "incidents similaires (RAG) et synthèse narrative (si Ollama disponible)."
    ),
)
def get_audit_report(snapshot_id: str, _user=_VIEW):
    from src.storage.sync_mongo_repository import get_audit_snapshot_by_id_sync

    doc = get_audit_snapshot_by_id_sync(snapshot_id)
    if not doc:
        raise HTTPException(404, detail="Rapport d'audit introuvable.")
    doc = dict(doc)
    doc["id"] = doc.pop("_id")
    return doc


@router.post(
    "/run",
    summary="Déclencher un audit manuellement",
    description=(
        "Exécute AuditAgent immédiatement (synchrone) et retourne le rapport "
        "généré. Admin uniquement — pensé pour la démo, en plus des jobs "
        "planifiés (scheduler.py)."
    ),
)
def run_audit_report(body: RunAuditReportRequest, _user=_RUN):
    _check_granularity(body.granularity)

    from src.ai_agents.audit_agent import AuditAgent

    result = AuditAgent().run({"granularity": body.granularity})
    if not result.success:
        raise HTTPException(500, detail=result.error or "Échec de la génération du rapport d'audit.")
    return result.output
