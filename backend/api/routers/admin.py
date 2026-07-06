"""Admin user management endpoints — ADMIN role only."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.auth import generate_temp_password, get_current_user, hash_password, require_role
from api.deps import get_session
from api.limiter import limiter, limit
from src.models.audit import AuditLogCreate
from src.services.audit_service import log_action, _ip, _ua

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
    is_demo: bool = False


@router.post(
    "/users",
    status_code=status.HTTP_201_CREATED,
    summary="Créer un utilisateur",
    description=(
        "Crée un nouveau compte utilisateur avec un mot de passe temporaire. "
        "L'utilisateur devra le changer à la première connexion. "
        "Réservé au rôle Admin. Limité à 5 créations par minute."
    ),
    response_description="ID, email et mot de passe temporaire généré",
    responses={
        403: {"description": "Rôle Admin requis"},
        409: {"description": "Email déjà utilisé"},
    },
)
@limiter.limit(limit("5/minute"))
def create_user(
    request: Request,
    body: UserCreateRequest,
    current_user: dict = Depends(get_current_user),
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
    session.flush()  # get user.id before log

    log_action(session, AuditLogCreate(
        user_id=current_user.get("sub"),
        user_email=current_user.get("email"),
        user_role=current_user.get("role"),
        action="CREATE",
        resource_type="User",
        resource_id=str(user.id),
        after_value={"email": user.email, "role": user.role, "departement": user.departement},
        status="SUCCESS",
        ip_address=_ip(request),
        user_agent=_ua(request),
    ))
    session.commit()
    session.refresh(user)

    from src.services.email_service import send_temp_password_email
    try:
        send_temp_password_email(user.email, temp_pw, user.prenom)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Impossible d'envoyer l'email de bienvenue : %s", exc)

    return {"user_id": str(user.id), "email": user.email}


@router.get(
    "/users",
    response_model=list[UserOut],
    summary="Lister les utilisateurs",
    description=(
        "Retourne tous les comptes : utilisateurs en base de données et comptes démo système. "
        "Les comptes démo sont marqués `is_demo=true` et n'ont pas d'actions disponibles."
    ),
    response_description="Liste complète des utilisateurs avec rôles et statuts",
    responses={403: {"description": "Rôle Admin requis"}},
)
def list_users(
    _: dict = _ADMIN,
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_users import UserORM
    from api.auth import USERS

    db_users = session.execute(select(UserORM).order_by(UserORM.created_at.desc())).scalars().all()
    db_emails = {u.email for u in db_users}

    result = [
        UserOut(
            id=str(u.id),
            nom=u.nom,
            prenom=u.prenom,
            email=u.email,
            role=u.role,
            departement=u.departement or "",
            is_first_login=u.is_first_login,
            is_active=u.is_active,
            created_at=u.created_at.isoformat(),
            is_demo=u.email in USERS,
        )
        for u in db_users
    ]

    # Append hardcoded demo accounts that are not in the DB
    for email, info in USERS.items():
        if email not in db_emails:
            slug = email.split("@")[0]
            result.append(UserOut(
                id=f"demo-{slug}",
                nom=slug.capitalize(),
                prenom="Demo",
                email=email,
                role=info["role"],
                departement="Demo",
                is_first_login=False,
                is_active=True,
                created_at="2026-01-01T00:00:00",
                is_demo=True,
            ))

    return result


@router.patch(
    "/users/{user_id}",
    response_model=UserOut,
    summary="Modifier un utilisateur",
    description="Modifie le rôle, le département ou le statut actif d'un compte utilisateur.",
    response_description="Utilisateur mis à jour",
    responses={
        403: {"description": "Rôle Admin requis"},
        404: {"description": "Utilisateur non trouvé"},
    },
)
def update_user(
    user_id: str,
    body: UserUpdateRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    _: dict = _ADMIN,
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_users import UserORM

    user = session.get(UserORM, UUID(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé.")

    before = {"role": user.role, "is_active": user.is_active, "departement": user.departement}
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        if body.is_active is False and user.role == "Admin":
            active_admins = session.execute(
                select(func.count(UserORM.id)).where(
                    UserORM.role == "Admin",
                    UserORM.is_active == True,  # noqa: E712
                )
            ).scalar_one()
            if active_admins <= 1:
                raise HTTPException(
                    status_code=409,
                    detail="Impossible de désactiver le dernier administrateur actif.",
                )
        user.is_active = body.is_active
    if body.departement is not None:
        user.departement = body.departement
    after = {"role": user.role, "is_active": user.is_active, "departement": user.departement}

    log_action(session, AuditLogCreate(
        user_id=current_user.get("sub"),
        user_email=current_user.get("email"),
        user_role=current_user.get("role"),
        action="UPDATE",
        resource_type="User",
        resource_id=user_id,
        before_value=before,
        after_value=after,
        status="SUCCESS",
        ip_address=_ip(request),
        user_agent=_ua(request),
    ))
    session.commit()
    session.refresh(user)
    return UserOut(
        id=str(user.id), nom=user.nom, prenom=user.prenom, email=user.email,
        role=user.role, departement=user.departement, is_first_login=user.is_first_login,
        is_active=user.is_active, created_at=user.created_at.isoformat(),
    )


@router.post(
    "/users/{user_id}/reset-password",
    summary="Réinitialiser le mot de passe",
    description=(
        "Génère un nouveau mot de passe temporaire et force le changement "
        "à la prochaine connexion (`is_first_login=true`)."
    ),
    response_description="Nouveau mot de passe temporaire à transmettre à l'utilisateur",
    responses={
        403: {"description": "Rôle Admin requis"},
        404: {"description": "Utilisateur non trouvé"},
    },
)
def reset_password(
    user_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
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

    log_action(session, AuditLogCreate(
        user_id=current_user.get("sub"),
        user_email=current_user.get("email"),
        user_role=current_user.get("role"),
        action="UPDATE",
        resource_type="User",
        resource_id=user_id,
        status="SUCCESS",
        detail=f"Mot de passe réinitialisé pour {user.email}",
        ip_address=_ip(request),
        user_agent=_ua(request),
    ))
    session.commit()

    from src.services.email_service import send_temp_password_email
    try:
        send_temp_password_email(user.email, temp_pw, user.prenom)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Impossible d'envoyer l'email de réinitialisation : %s", exc)

    return {"message": f"Mot de passe réinitialisé. Les nouvelles informations ont été envoyées à {user.email}."}
