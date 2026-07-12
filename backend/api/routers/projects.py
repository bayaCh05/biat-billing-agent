"""Projects / chartes endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from api.schemas import ProjectOut, ProjectPhaseOut

router = APIRouter(prefix="/projects", tags=["projects"])

_log = logging.getLogger(__name__)


def _phase_status(status: str, consumed_jh: float) -> str:
    if status in ("closed", "cancelled"):
        return "CLOSED"
    return "IN_PROGRESS" if consumed_jh > 0 else "OPEN"


@router.get(
    "",
    response_model=list[ProjectOut],
    summary="Lister les projets IT",
    description=(
        "Retourne tous les projets IT avec leur charte : budget en jours-hommes, "
        "consommation réelle, taux journalier et montants TND. "
        "Triés par date de démarrage décroissante."
    ),
    response_description="Liste de projets avec budgets JH et TND, consommation et statut",
)
async def list_projects():
    from src.storage.documents.service_bridge import list_projects_mongo

    mongo_result = await list_projects_mongo()
    if mongo_result is None:
        # Projects are written Mongo-only (see CLAUDE.md) — the old SQLite
        # fallback here could only ever serve permanently stale data.
        _log.warning("list_projects: MongoDB indisponible — retour d'une liste vide.")
        return []
    return [ProjectOut(**p) for p in mongo_result]


@router.get(
    "/{project_id}",
    response_model=ProjectOut,
    summary="Détails d'un projet",
    description="Retourne la charte et les indicateurs d'avancement d'un projet spécifique.",
    response_description="Projet avec budget JH, consommation et montants TND",
    responses={404: {"description": "Projet non trouvé"}},
)
async def get_project(project_id: str):
    from src.storage.documents.service_bridge import get_project_mongo

    mongo_result = await get_project_mongo(project_id)
    if mongo_result is None:
        # Projects are written Mongo-only (see CLAUDE.md) — the old SQLite
        # fallback here could only ever serve permanently stale data.
        _log.warning("get_project: MongoDB indisponible — %s introuvable.", project_id)
        raise HTTPException(status_code=404, detail="Projet non trouvé.")
    if not mongo_result:
        raise HTTPException(status_code=404, detail="Projet non trouvé.")
    return ProjectOut(**mongo_result)


@router.get(
    "/{project_id}/phases",
    response_model=list[ProjectPhaseOut],
    summary="Phases d'un projet",
    description=(
        "Liste toutes les phases d'un projet avec les jours-hommes planifiés "
        "vs consommés et le statut (OPEN, IN_PROGRESS, CLOSED)."
    ),
    response_description="Liste des phases avec avancement JH",
)
async def list_phases(project_id: str):
    from src.storage.documents.service_bridge import list_phases_mongo

    mongo_phases = await list_phases_mongo(project_id)
    if mongo_phases is None:
        # Phases are written Mongo-only (see CLAUDE.md) — the old SQLite
        # fallback here could only ever serve permanently stale data.
        _log.warning("list_phases: MongoDB indisponible — retour d'une liste vide.")
        return []
    return [
        ProjectPhaseOut(
            id=p.id, project_id=p.project_id, name=p.name,
            planned_jh=p.planned_jh, consumed_jh=p.consumed_jh,
            status=_phase_status(p.status, p.consumed_jh),
        )
        for p in mongo_phases
    ]
