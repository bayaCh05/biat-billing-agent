"""Current-user profile endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.deps import get_session

router = APIRouter(prefix="/users", tags=["users"])


class UserMeOut(BaseModel):
    id: str | None
    nom: str
    prenom: str
    email: str
    role: str
    departement: str
    created_at: str | None


class UserMeUpdateRequest(BaseModel):
    nom: str | None = None
    prenom: str | None = None
    departement: str | None = None


@router.get("/me", response_model=UserMeOut)
def get_me(
    current_user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_users import UserORM

    email = current_user.get("email")
    if not email:
        # Demo hardcoded user — synthesise from JWT claims
        role = current_user.get("role", "")
        demo_names = {
            "Comptable":      ("Baya", "C."),
            "Chef de Projet": ("Karim", "B."),
            "Direction":      ("Directeur", "IT"),
            "Admin":          ("Admin", "BIAT"),
        }
        nom, prenom = demo_names.get(role, ("Demo", "User"))
        return UserMeOut(
            id=None, nom=nom, prenom=prenom,
            email=f"{role.lower().replace(' ', '.')}@biat-it.tn",
            role=role, departement="", created_at=None,
        )

    user = session.execute(select(UserORM).where(UserORM.email == email)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé.")
    return UserMeOut(
        id=str(user.id), nom=user.nom, prenom=user.prenom, email=user.email,
        role=user.role, departement=user.departement,
        created_at=user.created_at.isoformat(),
    )


@router.patch("/me", response_model=UserMeOut)
def update_me(
    body: UserMeUpdateRequest,
    current_user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_users import UserORM

    email = current_user.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Modification non disponible pour les comptes de démonstration.")

    user = session.execute(select(UserORM).where(UserORM.email == email)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé.")

    if body.nom is not None:
        user.nom = body.nom
    if body.prenom is not None:
        user.prenom = body.prenom
    if body.departement is not None:
        user.departement = body.departement
    session.commit()
    session.refresh(user)
    return UserMeOut(
        id=str(user.id), nom=user.nom, prenom=user.prenom, email=user.email,
        role=user.role, departement=user.departement,
        created_at=user.created_at.isoformat(),
    )
