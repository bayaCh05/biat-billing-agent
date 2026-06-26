"""Authentication endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import USERS, create_token, get_current_user, hash_password, verify_password
from api.deps import get_session

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    role: str
    force_password_change: bool = False


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, session: Session = Depends(get_session)) -> LoginResponse:
    from src.storage.orm_models_users import UserORM

    email = body.email.lower().strip()

    # DB users take priority
    db_user = session.execute(select(UserORM).where(UserORM.email == email)).scalar_one_or_none()
    if db_user:
        if not db_user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Compte désactivé.")
        if not verify_password(body.password, db_user.hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email ou mot de passe incorrect.")
        extra = {
            "user_id": str(db_user.id),
            "email": db_user.email,
            "nom": db_user.nom,
            "prenom": db_user.prenom,
            "departement": db_user.departement,
            "force_password_change": db_user.is_first_login,
        }
        return LoginResponse(
            access_token=create_token(db_user.role, extra),
            token_type="bearer",
            role=db_user.role,
            force_password_change=db_user.is_first_login,
        )

    # Fall back to hardcoded demo users
    demo = USERS.get(email)
    if demo and demo["password"] == body.password:
        return LoginResponse(
            access_token=create_token(demo["role"]),
            token_type="bearer",
            role=demo["role"],
            force_password_change=False,
        )

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email ou mot de passe incorrect.")


@router.patch("/change-password")
def change_password(
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_users import UserORM

    email = current_user.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Changement de mot de passe non disponible pour les comptes de démonstration.")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail="Le mot de passe doit contenir au moins 8 caractères.")

    user = session.execute(select(UserORM).where(UserORM.email == email)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé.")
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Mot de passe actuel incorrect.")

    user.hashed_password = hash_password(body.new_password)
    user.is_first_login = False
    session.commit()
    return {"message": "Mot de passe modifié avec succès."}
