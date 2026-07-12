"""Feuille de route 2026 endpoints."""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from api.auth import require_role

router = APIRouter(prefix="/roadmap", tags=["roadmap"])

_log = logging.getLogger(__name__)

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


class RiskBriefOut(BaseModel):
    count: int
    highest_criticite: str | None


class RoadmapItemWithRisks(RoadmapItemOut):
    days_overdue: int
    is_late: bool
    days_until_due: int
    risk_summary: RiskBriefOut


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
async def list_roadmap(
    annee: int = Query(2026),
):
    from src.storage.documents.service_bridge import list_roadmap_mongo

    mongo_items = await list_roadmap_mongo(annee)
    if mongo_items is None:
        # Roadmap is written Mongo-only (see CLAUDE.md) — the old SQLite
        # fallback here could only ever serve permanently stale data, so it
        # was removed rather than kept as a silent source of "old data" bugs.
        _log.warning(
            "list_roadmap: MongoDB indisponible — retour d'une liste vide (annee=%s).", annee,
        )
        return []
    return [_to_out(i) for i in mongo_items]


@router.get(
    "/with-risks",
    response_model=list[RoadmapItemWithRisks],
    summary="Roadmap avec résumé des risques et indicateurs de retard",
    description=(
        "Retourne tous les jalons enrichis avec : "
        "days_overdue, is_late, days_until_due, et un résumé des risques liés "
        "(count + niveau de criticité le plus élevé). "
        "Une seule requête — pas de N+1."
    ),
)
async def list_roadmap_with_risks(
    annee: int = Query(2026),
):
    from src.storage.documents.service_bridge import list_roadmap_with_risks_mongo

    today = date.today()

    mongo_result = await list_roadmap_with_risks_mongo(annee)
    if mongo_result is None:
        # Roadmap + risks are written Mongo-only (see CLAUDE.md) — the old
        # SQLite fallback here could only ever serve permanently stale data.
        _log.warning(
            "list_roadmap_with_risks: MongoDB indisponible — retour d'une liste vide "
            "(annee=%s).", annee,
        )
        return []

    result: list[RoadmapItemWithRisks] = []
    for item in mongo_result["items"]:
        item_id = str(item.id)
        days_until_due = (item.date_fin - today).days
        is_late = days_until_due < 0 and item.statut not in ("TERMINE", "ANNULE")
        days_overdue = max(0, -days_until_due) if is_late else 0
        rs = mongo_result["risk_by_item"].get(item_id, {"count": 0, "highest_criticite": None})
        result.append(RoadmapItemWithRisks(
            **_to_out(item).model_dump(),
            days_overdue=days_overdue,
            is_late=is_late,
            days_until_due=days_until_due,
            risk_summary=RiskBriefOut(**rs),
        ))
    return result


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
async def create_roadmap_item(
    body: RoadmapCreateRequest,
    _: dict = _EDIT,
):
    from src.storage.documents.service_bridge import create_roadmap_item_native

    item = await create_roadmap_item_native(body)
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
async def update_roadmap_item(
    item_id: str,
    body: RoadmapUpdateRequest,
    _: dict = _EDIT,
):
    from src.storage.documents.service_bridge import update_roadmap_item_native

    item = await update_roadmap_item_native(item_id, body)
    if not item:
        raise HTTPException(status_code=404, detail="Item non trouvé.")
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
async def delete_roadmap_item(
    item_id: str,
    _: dict = _EDIT,
):
    from src.storage.documents.service_bridge import delete_roadmap_item_native

    found = await delete_roadmap_item_native(item_id)
    if not found:
        raise HTTPException(status_code=404, detail="Item non trouvé.")
