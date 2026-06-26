"""Project budget line endpoints."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import require_role
from api.deps import get_session

router = APIRouter(tags=["projet-budget"])

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


@router.get("/projets/{projet_id}/budget", response_model=list[LigneBudgetOut])
def list_budget(projet_id: str, session: Session = Depends(get_session)):
    from src.storage.orm_models_extra import LigneBudgetORM

    lignes = session.execute(
        select(LigneBudgetORM).where(LigneBudgetORM.projet_id == projet_id)
        .order_by(LigneBudgetORM.created_at)
    ).scalars().all()
    return [_to_out(l) for l in lignes]


@router.post("/projets/{projet_id}/budget", response_model=LigneBudgetOut, status_code=status.HTTP_201_CREATED)
def create_budget_line(
    projet_id: str,
    body: LigneBudgetCreateRequest,
    _: dict = _EDIT,
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_extra import LigneBudgetORM

    lb = LigneBudgetORM(
        projet_id=projet_id,
        categorie=body.categorie,
        montant_prevu=body.montant_prevu,
        devise=body.devise,
    )
    session.add(lb)
    session.commit()
    session.refresh(lb)
    return _to_out(lb)


@router.patch("/projet-budget/{ligne_id}", response_model=LigneBudgetOut)
def update_budget_line(
    ligne_id: str,
    body: LigneBudgetUpdateRequest,
    _: dict = _EDIT,
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_extra import LigneBudgetORM

    lb = session.get(LigneBudgetORM, UUID(ligne_id))
    if not lb:
        raise HTTPException(status_code=404, detail="Ligne budget non trouvée.")
    if body.categorie is not None:    lb.categorie = body.categorie
    if body.montant_prevu is not None: lb.montant_prevu = body.montant_prevu
    session.commit()
    session.refresh(lb)
    return _to_out(lb)


@router.delete("/projet-budget/{ligne_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget_line(
    ligne_id: str,
    _: dict = _EDIT,
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_extra import LigneBudgetORM

    lb = session.get(LigneBudgetORM, UUID(ligne_id))
    if not lb:
        raise HTTPException(status_code=404, detail="Ligne budget non trouvée.")
    session.delete(lb)
    session.commit()


@router.get("/projets/{projet_id}/budget/synthese", response_model=BudgetSyntheseOut)
def budget_synthese(projet_id: str, session: Session = Depends(get_session)):
    from src.storage.orm_models_extra import LigneBudgetORM

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
