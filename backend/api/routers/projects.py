"""Projects / chartes endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_session
from api.schemas import ProjectOut, ProjectPhaseOut
from src.storage.orm_models_projects import CharteProjetORM, PhaseORM

router = APIRouter(prefix="/projects", tags=["projects"])


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
async def list_projects(session: Session = Depends(get_session)):
    from src.storage.documents.service_bridge import list_projects_mongo

    mongo_result = await list_projects_mongo()
    if mongo_result is not None:
        return [ProjectOut(**p) for p in mongo_result]

    chartes = session.execute(
        select(CharteProjetORM).order_by(CharteProjetORM.valid_from.desc())
    ).scalars().all()

    result = []
    for c in chartes:
        phases = session.execute(
            select(PhaseORM).where(PhaseORM.project_id == c.project_id)
        ).scalars().all()
        consumed_jh = sum(p.consumed_jh for p in phases)
        result.append(ProjectOut(
            id=c.project_id,
            name=c.project_name,
            client=c.client,
            budget_jh=c.budget_jh,
            consumed_jh=consumed_jh,
            taux_jh=c.taux_jh,
            status="ACTIVE" if c.is_active else "COMPLETED",
            start_date=c.valid_from.isoformat(),
            end_date=c.valid_until.isoformat() if c.valid_until else None,
            budget_tnd=round(c.budget_jh * c.taux_jh, 3),
            spent_tnd=round(consumed_jh * c.taux_jh, 3),
        ))
    return result


@router.get(
    "/{project_id}",
    response_model=ProjectOut,
    summary="Détails d'un projet",
    description="Retourne la charte et les indicateurs d'avancement d'un projet spécifique.",
    response_description="Projet avec budget JH, consommation et montants TND",
    responses={404: {"description": "Projet non trouvé"}},
)
async def get_project(project_id: str, session: Session = Depends(get_session)):
    from src.storage.documents.service_bridge import get_project_mongo

    mongo_result = await get_project_mongo(project_id)
    if mongo_result is not None:
        if not mongo_result:
            raise HTTPException(status_code=404, detail="Projet non trouvé.")
        return ProjectOut(**mongo_result)

    charte = session.execute(
        select(CharteProjetORM).where(CharteProjetORM.project_id == project_id)
    ).scalar_one_or_none()
    if not charte:
        raise HTTPException(status_code=404, detail="Projet non trouvé.")
    phases = session.execute(
        select(PhaseORM).where(PhaseORM.project_id == project_id)
    ).scalars().all()
    consumed_jh = sum(p.consumed_jh for p in phases)
    return ProjectOut(
        id=charte.project_id, name=charte.project_name, client=charte.client,
        budget_jh=charte.budget_jh, consumed_jh=consumed_jh, taux_jh=charte.taux_jh,
        status="ACTIVE" if charte.is_active else "COMPLETED",
        start_date=charte.valid_from.isoformat(),
        end_date=charte.valid_until.isoformat() if charte.valid_until else None,
        budget_tnd=round(charte.budget_jh * charte.taux_jh, 3),
        spent_tnd=round(consumed_jh * charte.taux_jh, 3),
    )


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
async def list_phases(project_id: str, session: Session = Depends(get_session)):
    from src.storage.documents.service_bridge import list_phases_mongo

    mongo_phases = await list_phases_mongo(project_id)
    if mongo_phases is not None:
        return [
            ProjectPhaseOut(
                id=p.id, project_id=p.project_id, name=p.name,
                planned_jh=p.planned_jh, consumed_jh=p.consumed_jh,
                status=_phase_status(p.status, p.consumed_jh),
            )
            for p in mongo_phases
        ]

    phases = session.execute(
        select(PhaseORM)
        .where(PhaseORM.project_id == project_id)
        .order_by(PhaseORM.id)
    ).scalars().all()
    return [
        ProjectPhaseOut(
            id=p.id,
            project_id=p.project_id,
            name=p.name,
            planned_jh=p.planned_jh,
            consumed_jh=p.consumed_jh,
            status=_phase_status(p.status, p.consumed_jh),
        )
        for p in phases
    ]
