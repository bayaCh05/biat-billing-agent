"""Admin user management endpoints — ADMIN role only."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from api.auth import generate_temp_password, get_current_user, hash_password, require_role
from api.limiter import limiter, limit
from src.models.audit import AuditLogCreate
from src.services.audit_service import _ip, _ua

router = APIRouter(prefix="/admin", tags=["admin"])

_log = logging.getLogger(__name__)

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
async def create_user(
    request: Request,
    body: UserCreateRequest,
    current_user: dict = Depends(get_current_user),
    _: dict = _ADMIN,
):
    from src.storage.documents.service_bridge import create_user_native, log_audit_event_native

    temp_pw = generate_temp_password()
    user = await create_user_native(
        nom=body.nom, prenom=body.prenom, email=body.email.lower().strip(),
        hashed_password=hash_password(temp_pw), role=body.role, departement=body.departement,
    )
    if user is None:
        raise HTTPException(status_code=409, detail="Un utilisateur avec cet email existe déjà.")

    await log_audit_event_native(AuditLogCreate(
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
async def list_users(
    _: dict = _ADMIN,
):
    from api.auth import USERS
    from src.storage.documents.service_bridge import list_users_mongo

    mongo_users = await list_users_mongo()
    if mongo_users is None:
        # Users are written Mongo-only (see CLAUDE.md) — the old SQLite
        # fallback here could only ever serve permanently stale data.
        _log.warning("list_users: MongoDB indisponible — retour d'une liste vide.")
        db_users = []
    else:
        db_users = mongo_users
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
async def update_user(
    user_id: str,
    body: UserUpdateRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    _: dict = _ADMIN,
):
    from src.storage.documents.service_bridge import (
        get_user_by_id_native, log_audit_event_native, update_user_admin_native,
    )

    existing = await get_user_by_id_native(user_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé.")
    before = {"role": existing.role, "is_active": existing.is_active, "departement": existing.departement}

    user = await update_user_admin_native(user_id, body.role, body.is_active, body.departement)
    if user == "LAST_ADMIN":
        raise HTTPException(
            status_code=409,
            detail="Impossible de désactiver le dernier administrateur actif.",
        )
    after = {"role": user.role, "is_active": user.is_active, "departement": user.departement}

    await log_audit_event_native(AuditLogCreate(
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
async def reset_password(
    user_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
    _: dict = _ADMIN,
):
    from src.storage.documents.service_bridge import (
        get_user_by_id_native, log_audit_event_native,
        revoke_all_user_tokens_native, update_user_password_native,
    )

    user = await get_user_by_id_native(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé.")

    temp_pw = generate_temp_password()
    await update_user_password_native(user_id, hash_password(temp_pw), is_first_login=True)

    # Revoke ALL of the target user's sessions — an Admin resetting someone's
    # password is very often a response to a compromised/stolen token, so the
    # attacker's session must not survive it. There's no session of the
    # target user to preserve (the acting session here is the Admin's own).
    revoked_count = await revoke_all_user_tokens_native(
        user_id, except_jti=None, reason="admin_password_reset",
    )

    await log_audit_event_native(AuditLogCreate(
        user_id=current_user.get("sub"),
        user_email=current_user.get("email"),
        user_role=current_user.get("role"),
        action="UPDATE",
        resource_type="User",
        resource_id=user_id,
        status="SUCCESS",
        detail=f"Mot de passe réinitialisé pour {user.email} — {revoked_count} session(s) révoquée(s)",
        ip_address=_ip(request),
        user_agent=_ua(request),
    ))

    from src.services.email_service import send_temp_password_email
    try:
        send_temp_password_email(user.email, temp_pw, user.prenom)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Impossible d'envoyer l'email de réinitialisation : %s", exc)

    return {"message": f"Mot de passe réinitialisé. Les nouvelles informations ont été envoyées à {user.email}."}
