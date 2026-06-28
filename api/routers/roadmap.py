"""Feuille de route 2026 endpoints."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import require_role
from api.deps import get_session

router = APIRouter(prefix="/roadmap", tags=["roadmap"])

_EDIT = Depends(require_role("Chef de Projet", "Admin"))


class RoadmapItemOut(BaseModel):
    id: str
    titre: str
    description: str
    date_debut: str
    date_fin: str
    projet_id: str | None
    responsable_id: str | None
    statut: str
    priorite: str
    annee: int


class RoadmapCreateRequest(BaseModel):
    titre: str
    description: str = ""
    date_debut: date
    date_fin: date
    projet_id: str | None = None
    responsable_id: str | None = None
    statut: str = "PLANIFIE"
    priorite: str = "MOYENNE"
    annee: int = 2026


class RoadmapUpdateRequest(BaseModel):
    titre: str | None = None
    description: str | None = None
    date_debut: date | None = None
    date_fin: date | None = None
    statut: str | None = None
    priorite: str | None = None
    projet_id: str | None = None


def _to_out(r) -> RoadmapItemOut:
    return RoadmapItemOut(
        id=str(r.id), titre=r.titre, description=r.description,
        date_debut=r.date_debut.isoformat(), date_fin=r.date_fin.isoformat(),
        projet_id=r.projet_id, responsable_id=r.responsable_id,
        statut=r.statut, priorite=r.priorite, annee=r.annee,
    )


@router.get(
    "",
    response_model=list[RoadmapItemOut],
    summary="Lister la feuille de route",
    description=(
        "Retourne les jalons de la feuille de route filtrés par année, "
        "triés par date de début. "
        "Statuts : PLANIFIE, EN_COURS, TERMINE, ANNULE. "
        "Priorités : HAUTE, MOYENNE, BASSE."
    ),
    response_description="Liste des jalons de la roadmap pour l'année demandée",
)
def list_roadmap(
    annee: int = Query(2026),
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_extra import FeuilleDeRouteORM

    items = session.execute(
        select(FeuilleDeRouteORM)
        .where(FeuilleDeRouteORM.annee == annee)
        .order_by(FeuilleDeRouteORM.date_debut)
    ).scalars().all()
    return [_to_out(i) for i in items]


@router.post(
    "",
    response_model=RoadmapItemOut,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un jalon",
    description=(
        "Ajoute un nouveau jalon à la feuille de route. "
        "Accès réservé aux rôles Chef de Projet et Admin."
    ),
    response_description="Jalon créé avec son identifiant UUID",
    responses={403: {"description": "Rôle Chef de Projet ou Admin requis"}},
)
def create_roadmap_item(
    body: RoadmapCreateRequest,
    _: dict = _EDIT,
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_extra import FeuilleDeRouteORM

    item = FeuilleDeRouteORM(
        titre=body.titre, description=body.description,
        date_debut=body.date_debut, date_fin=body.date_fin,
        projet_id=body.projet_id, responsable_id=body.responsable_id,
        statut=body.statut, priorite=body.priorite, annee=body.annee,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return _to_out(item)


@router.patch(
    "/{item_id}",
    response_model=RoadmapItemOut,
    summary="Mettre à jour un jalon",
    description="Modifie le titre, les dates, le statut ou la priorité d'un jalon existant.",
    response_description="Jalon mis à jour",
    responses={
        403: {"description": "Rôle Chef de Projet ou Admin requis"},
        404: {"description": "Jalon non trouvé"},
    },
)
def update_roadmap_item(
    item_id: str,
    body: RoadmapUpdateRequest,
    _: dict = _EDIT,
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_extra import FeuilleDeRouteORM

    item = session.get(FeuilleDeRouteORM, UUID(item_id))
    if not item:
        raise HTTPException(status_code=404, detail="Item non trouvé.")
    if body.titre is not None:      item.titre = body.titre
    if body.description is not None: item.description = body.description
    if body.date_debut is not None:  item.date_debut = body.date_debut
    if body.date_fin is not None:    item.date_fin = body.date_fin
    if body.statut is not None:      item.statut = body.statut
    if body.priorite is not None:    item.priorite = body.priorite
    if body.projet_id is not None:   item.projet_id = body.projet_id
    session.commit()
    session.refresh(item)
    return _to_out(item)


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer un jalon",
    description="Supprime définitivement un jalon de la feuille de route.",
    responses={
        403: {"description": "Rôle Chef de Projet ou Admin requis"},
        404: {"description": "Jalon non trouvé"},
    },
)
def delete_roadmap_item(
    item_id: str,
    _: dict = _EDIT,
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_extra import FeuilleDeRouteORM

    item = session.get(FeuilleDeRouteORM, UUID(item_id))
    if not item:
        raise HTTPException(status_code=404, detail="Item non trouvé.")
    session.delete(item)
    session.commit()
