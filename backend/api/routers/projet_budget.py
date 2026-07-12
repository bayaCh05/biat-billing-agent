"""Project budget line endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import require_role
from api.deps import get_session

router = APIRouter(tags=["budget"])

_EDIT = Depends(require_role("Comptable", "Chef de Projet", "Admin"))


class LigneBudgetOut(BaseModel):
    id: str
    projet_id: str
    categorie: str
    montant_prevu: float
    montant_consomme: float
    devise: str
    ecart: float
    taux_consommation: float


class LigneBudgetCreateRequest(BaseModel):
    categorie: str
    montant_prevu: float
    devise: str = "TND"


class LigneBudgetUpdateRequest(BaseModel):
    categorie: str | None = None
    montant_prevu: float | None = None


class BudgetSyntheseOut(BaseModel):
    total_prevu: float
    total_consomme: float
    ecart: float
    taux_consommation: float


def _to_out(lb) -> LigneBudgetOut:
    ecart = lb.montant_prevu - lb.montant_consomme
    taux = round(lb.montant_consomme / lb.montant_prevu * 100, 1) if lb.montant_prevu > 0 else 0.0
    return LigneBudgetOut(
        id=str(lb.id), projet_id=lb.projet_id, categorie=lb.categorie,
        montant_prevu=lb.montant_prevu, montant_consomme=lb.montant_consomme,
        devise=lb.devise, ecart=ecart, taux_consommation=taux,
    )


@router.get(
    "/projets/{projet_id}/budget",
    response_model=list[LigneBudgetOut],
    summary="Lignes budgétaires d'un projet",
    description=(
        "Retourne toutes les lignes budgétaires d'un projet IT : "
        "montant prévu, montant consommé, écart et taux de consommation en pourcentage."
    ),
    response_description="Liste des lignes avec indicateurs d'avancement budgétaire",
)
async def list_budget(projet_id: str, session: Session = Depends(get_session)):
    from src.storage.documents.service_bridge import list_budget_lines_mongo

    mongo_lignes = await list_budget_lines_mongo(projet_id)
    if mongo_lignes is not None:
        return [_to_out(l) for l in mongo_lignes]

    from src.storage.orm_models_roadmap import LigneBudgetORM

    lignes = session.execute(
        select(LigneBudgetORM).where(LigneBudgetORM.projet_id == projet_id)
        .order_by(LigneBudgetORM.created_at)
    ).scalars().all()
    return [_to_out(l) for l in lignes]


@router.post(
    "/projets/{projet_id}/budget",
    response_model=LigneBudgetOut,
    status_code=status.HTTP_201_CREATED,
    summary="Ajouter une ligne budgétaire",
    description=(
        "Crée une nouvelle ligne budgétaire pour un projet. "
        "Rôles autorisés : Comptable, Chef de Projet, Admin."
    ),
    response_description="Ligne budgétaire créée",
    responses={403: {"description": "Permissions insuffisantes"}},
)
async def create_budget_line(
    projet_id: str,
    body: LigneBudgetCreateRequest,
    _: dict = _EDIT,
):
    from src.storage.documents.service_bridge import create_budget_line_native

    lb = await create_budget_line_native(projet_id, body)
    return _to_out(lb)


@router.patch(
    "/projet-budget/{ligne_id}",
    response_model=LigneBudgetOut,
    summary="Modifier une ligne budgétaire",
    description="Met à jour la catégorie ou le montant prévu d'une ligne budgétaire.",
    response_description="Ligne budgétaire mise à jour",
    responses={
        403: {"description": "Permissions insuffisantes"},
        404: {"description": "Ligne budgétaire non trouvée"},
    },
)
async def update_budget_line(
    ligne_id: str,
    body: LigneBudgetUpdateRequest,
    _: dict = _EDIT,
):
    from src.storage.documents.service_bridge import update_budget_line_native

    lb = await update_budget_line_native(ligne_id, body)
    if not lb:
        raise HTTPException(status_code=404, detail="Ligne budget non trouvée.")
    return _to_out(lb)


@router.delete(
    "/projet-budget/{ligne_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer une ligne budgétaire",
    description="Supprime définitivement une ligne budgétaire d'un projet.",
    responses={
        403: {"description": "Permissions insuffisantes"},
        404: {"description": "Ligne budgétaire non trouvée"},
    },
)
async def delete_budget_line(
    ligne_id: str,
    _: dict = _EDIT,
):
    from src.storage.documents.service_bridge import delete_budget_line_native

    found = await delete_budget_line_native(ligne_id)
    if not found:
        raise HTTPException(status_code=404, detail="Ligne budget non trouvée.")


@router.get(
    "/projets/{projet_id}/budget/synthese",
    response_model=BudgetSyntheseOut,
    summary="Synthèse budgétaire d'un projet",
    description=(
        "Retourne les totaux consolidés du budget d'un projet : "
        "montant total prévu, total consommé, écart absolu et taux de consommation global."
    ),
    response_description="Synthèse avec totaux et taux de consommation",
)
async def budget_synthese(projet_id: str, session: Session = Depends(get_session)):
    from src.storage.documents.service_bridge import budget_synthese_mongo

    mongo_result = await budget_synthese_mongo(projet_id)
    if mongo_result is not None:
        return BudgetSyntheseOut(**mongo_result)

    from src.storage.orm_models_roadmap import LigneBudgetORM

    lignes = session.execute(
        select(LigneBudgetORM).where(LigneBudgetORM.projet_id == projet_id)
    ).scalars().all()
    total_prevu = sum(l.montant_prevu for l in lignes)
    total_consomme = sum(l.montant_consomme for l in lignes)
    ecart = total_prevu - total_consomme
    taux = round(total_consomme / total_prevu * 100, 1) if total_prevu > 0 else 0.0
    return BudgetSyntheseOut(
        total_prevu=total_prevu, total_consomme=total_consomme,
        ecart=ecart, taux_consommation=taux,
    )
