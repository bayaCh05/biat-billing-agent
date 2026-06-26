"""Livrables and phase validation endpoints."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import get_current_user, require_role
from api.deps import get_session

router = APIRouter(tags=["livrables"])

_EDIT = Depends(require_role("Chef de Projet", "Admin"))


class LivrableOut(BaseModel):
    id: str
    phase_id: str
    titre: str
    description: str
    date_livraison_prevue: str
    date_livraison_reelle: str | None
    statut: str
    fichier_path: str | None
    created_by: str


class LivrableCreateRequest(BaseModel):
    titre: str
    description: str = ""
    date_livraison_prevue: date
    statut: str = "EN_ATTENTE"


class LivrableUpdateRequest(BaseModel):
    titre: str | None = None
    description: str | None = None
    statut: str | None = None
    date_livraison_reelle: date | None = None


def _to_out(lv) -> LivrableOut:
    return LivrableOut(
        id=str(lv.id), phase_id=lv.phase_id, titre=lv.titre, description=lv.description,
        date_livraison_prevue=lv.date_livraison_prevue.isoformat(),
        date_livraison_reelle=lv.date_livraison_reelle.isoformat() if lv.date_livraison_reelle else None,
        statut=lv.statut, fichier_path=lv.fichier_path, created_by=lv.created_by,
    )


@router.get("/phases/{phase_id}/livrables", response_model=list[LivrableOut])
def list_livrables(phase_id: str, session: Session = Depends(get_session)):
    from src.storage.orm_models_extra import LivrableORM

    items = session.execute(
        select(LivrableORM).where(LivrableORM.phase_id == phase_id)
        .order_by(LivrableORM.date_livraison_prevue)
    ).scalars().all()
    return [_to_out(i) for i in items]


@router.post("/phases/{phase_id}/livrables", response_model=LivrableOut, status_code=status.HTTP_201_CREATED)
def create_livrable(
    phase_id: str,
    body: LivrableCreateRequest,
    current_user: dict = Depends(get_current_user),
    _: dict = _EDIT,
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_extra import LivrableORM
    from src.storage.orm_models_projects import PhaseORM

    phase = session.get(PhaseORM, phase_id)
    if not phase:
        raise HTTPException(status_code=404, detail="Phase non trouvée.")

    lv = LivrableORM(
        phase_id=phase_id, titre=body.titre, description=body.description,
        date_livraison_prevue=body.date_livraison_prevue, statut=body.statut,
        created_by=current_user.get("email", current_user.get("role", "")),
    )
    session.add(lv)
    session.commit()
    session.refresh(lv)
    return _to_out(lv)


@router.patch("/livrables/{livrable_id}", response_model=LivrableOut)
def update_livrable(
    livrable_id: str,
    body: LivrableUpdateRequest,
    _: dict = _EDIT,
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_extra import LivrableORM

    lv = session.get(LivrableORM, UUID(livrable_id))
    if not lv:
        raise HTTPException(status_code=404, detail="Livrable non trouvé.")
    if body.titre is not None:               lv.titre = body.titre
    if body.description is not None:         lv.description = body.description
    if body.statut is not None:              lv.statut = body.statut
    if body.date_livraison_reelle is not None: lv.date_livraison_reelle = body.date_livraison_reelle
    session.commit()
    session.refresh(lv)
    return _to_out(lv)


@router.post("/phases/{phase_id}/valider")
def valider_phase(
    phase_id: str,
    _: dict = _EDIT,
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_extra import LivrableORM
    from src.storage.orm_models_projects import PhaseORM

    phase = session.get(PhaseORM, phase_id)
    if not phase:
        raise HTTPException(status_code=404, detail="Phase non trouvée.")

    livrables = session.execute(
        select(LivrableORM).where(LivrableORM.phase_id == phase_id)
    ).scalars().all()

    non_termines = [l for l in livrables if l.statut not in ("LIVRE", "VALIDE")]
    if non_termines:
        raise HTTPException(
            status_code=400,
            detail=f"{len(non_termines)} livrable(s) non terminé(s) — tous doivent être LIVRE ou VALIDE avant validation.",
        )

    phase.status = "VALIDEE"
    from datetime import date as date_cls
    phase.closed_date = date_cls.today()
    session.commit()
    return {"message": f"Phase '{phase.name}' validée avec succès.", "status": "VALIDEE"}
