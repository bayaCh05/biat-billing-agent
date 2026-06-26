"""Admin user management endpoints — ADMIN role only."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import generate_temp_password, hash_password, require_role
from api.deps import get_session

router = APIRouter(prefix="/admin", tags=["admin"])

_ADMIN = Depends(require_role("Admin"))


class UserCreateRequest(BaseModel):
    nom: str
    prenom: str
    email: str
    role: str                 # Comptable | Chef de Projet | Direction
    departement: str = ""


class UserUpdateRequest(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    departement: str | None = None


class UserOut(BaseModel):
    id: str
    nom: str
    prenom: str
    email: str
    role: str
    departement: str
    is_first_login: bool
    is_active: bool
    created_at: str


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreateRequest,
    _: dict = _ADMIN,
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_users import UserORM

    existing = session.execute(
        select(UserORM).where(UserORM.email == body.email.lower().strip())
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Un utilisateur avec cet email existe déjà.")

    temp_pw = generate_temp_password()
    user = UserORM(
        nom=body.nom,
        prenom=body.prenom,
        email=body.email.lower().strip(),
        hashed_password=hash_password(temp_pw),
        role=body.role,
        departement=body.departement,
        is_first_login=True,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return {"user_id": str(user.id), "email": user.email, "temp_password": temp_pw}


@router.get("/users", response_model=list[UserOut])
def list_users(
    _: dict = _ADMIN,
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_users import UserORM

    users = session.execute(select(UserORM).order_by(UserORM.created_at.desc())).scalars().all()
    return [
        UserOut(
            id=str(u.id),
            nom=u.nom,
            prenom=u.prenom,
            email=u.email,
            role=u.role,
            departement=u.departement,
            is_first_login=u.is_first_login,
            is_active=u.is_active,
            created_at=u.created_at.isoformat(),
        )
        for u in users
    ]


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    body: UserUpdateRequest,
    _: dict = _ADMIN,
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_users import UserORM

    user = session.get(UserORM, UUID(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé.")

    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.departement is not None:
        user.departement = body.departement
    session.commit()
    session.refresh(user)
    return UserOut(
        id=str(user.id), nom=user.nom, prenom=user.prenom, email=user.email,
        role=user.role, departement=user.departement, is_first_login=user.is_first_login,
        is_active=user.is_active, created_at=user.created_at.isoformat(),
    )


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: str,
    _: dict = _ADMIN,
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_users import UserORM

    user = session.get(UserORM, UUID(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé.")

    temp_pw = generate_temp_password()
    user.hashed_password = hash_password(temp_pw)
    user.is_first_login = True
    session.commit()
    return {"temp_password": temp_pw}
