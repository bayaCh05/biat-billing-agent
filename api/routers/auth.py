"""Authentication endpoints."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import USERS, create_token, get_current_user, hash_password, verify_password
from api.deps import get_session
from api.limiter import limiter, limit
from src.models.audit import AuditLogCreate
from src.services.audit_service import log_action, _ip, _ua

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


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Connexion utilisateur",
    description=(
        "Authentification par email et mot de passe. "
        "Accepte les comptes base de données et les comptes démo système. "
        "Limité à 5 tentatives par minute par IP pour prévenir les attaques par force brute."
    ),
    response_description="Token JWT Bearer valide 8h avec le rôle de l'utilisateur",
    responses={401: {"description": "Email ou mot de passe incorrect"}},
)
@limiter.limit(limit("5/minute"))
def login(request: Request, body: LoginRequest, session: Session = Depends(get_session)) -> LoginResponse:
    from src.storage.orm_models_users import UserORM

    email = body.email.lower().strip()
    ip = _ip(request)
    ua = _ua(request)

    # DB users take priority
    db_user = session.execute(select(UserORM).where(UserORM.email == email)).scalar_one_or_none()
    if db_user:
        if not db_user.is_active:
            log_action(session, AuditLogCreate(
                user_email=email, action="LOGIN", resource_type="User",
                resource_id=str(db_user.id), status="FAILURE",
                detail="Compte désactivé", ip_address=ip, user_agent=ua,
            ))
            session.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Compte désactivé.")
        if not verify_password(body.password, db_user.hashed_password):
            log_action(session, AuditLogCreate(
                user_email=email, action="LOGIN", resource_type="User",
                resource_id=str(db_user.id), status="FAILURE",
                detail="Mot de passe incorrect", ip_address=ip, user_agent=ua,
            ))
            session.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email ou mot de passe incorrect.")

        log_action(session, AuditLogCreate(
            user_id=str(db_user.id), user_email=db_user.email, user_role=db_user.role,
            action="LOGIN", resource_type="User", resource_id=str(db_user.id),
            status="SUCCESS", ip_address=ip, user_agent=ua,
        ))
        extra = {
            "user_id": str(db_user.id),
            "email": db_user.email,
            "nom": db_user.nom,
            "prenom": db_user.prenom,
            "departement": db_user.departement,
            "force_password_change": db_user.is_first_login,
        }
        session.commit()
        return LoginResponse(
            access_token=create_token(db_user.role, extra),
            token_type="bearer",
            role=db_user.role,
            force_password_change=db_user.is_first_login,
        )

    # Fall back to hardcoded demo users
    demo = USERS.get(email)
    if demo and secrets.compare_digest(demo["password"], body.password):
        log_action(session, AuditLogCreate(
            user_email=email, user_role=demo["role"],
            action="LOGIN", resource_type="User", status="SUCCESS",
            detail="Compte démo", ip_address=ip, user_agent=ua,
        ))
        session.commit()
        return LoginResponse(
            access_token=create_token(demo["role"]),
            token_type="bearer",
            role=demo["role"],
            force_password_change=False,
        )

    # Unknown user — log failed attempt
    log_action(session, AuditLogCreate(
        user_email=email, action="LOGIN", resource_type="User",
        status="FAILURE", detail="Utilisateur inconnu", ip_address=ip, user_agent=ua,
    ))
    session.commit()
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email ou mot de passe incorrect.")


@router.patch(
    "/change-password",
    summary="Changer le mot de passe",
    description=(
        "Modifie le mot de passe du compte connecté. "
        "Requiert l'ancien mot de passe pour confirmation. "
        "Non disponible pour les comptes démo. "
        "Limité à 3 tentatives par minute."
    ),
    response_description="Message de confirmation",
    responses={
        400: {"description": "Mot de passe actuel incorrect ou compte démo"},
        404: {"description": "Utilisateur non trouvé"},
    },
)
@limiter.limit(limit("3/minute"))
def change_password(
    request: Request,
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
    log_action(session, AuditLogCreate(
        user_id=str(user.id), user_email=user.email, user_role=user.role,
        action="UPDATE", resource_type="User", resource_id=str(user.id),
        status="SUCCESS", detail="Mot de passe changé",
        ip_address=_ip(request), user_agent=_ua(request),
    ))
    session.commit()
    return {"message": "Mot de passe modifié avec succès."}
