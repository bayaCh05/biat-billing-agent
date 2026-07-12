"""Current-user profile endpoints."""
from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.auth import get_current_user
from api.limiter import limiter, limit

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["admin"])

_AVATAR_MAX_BYTES = 2 * 1024 * 1024   # 2 Mo décodé
_AVATAR_MAX_STR   = 4 * 1024 * 1024   # garde-fou sur la chaîne brute (~3 Mo binaire)


class UserMeOut(BaseModel):
    id: str | None
    nom: str
    prenom: str
    email: str
    role: str
    departement: str
    created_at: str | None
    profile_picture: str | None = None


class UserMeUpdateRequest(BaseModel):
    nom: str | None = None
    prenom: str | None = None
    departement: str | None = None


class AvatarUpdateRequest(BaseModel):
    avatar: str   # chaîne complète data:image/...;base64,<données>


def _build_me(user) -> UserMeOut:
    return UserMeOut(
        id=str(user.id),
        nom=user.nom,
        prenom=user.prenom,
        email=user.email,
        role=user.role,
        departement=user.departement,
        created_at=user.created_at.isoformat(),
        profile_picture=user.profile_picture,
    )


def _demo_me(role: str, email: str) -> UserMeOut:
    demo_names = {
        "Comptable":      ("Baya", "C."),
        "Chef de Projet": ("Karim", "B."),
        "Direction":      ("Directeur", "IT"),
        "Admin":          ("Admin", "BIAT"),
    }
    nom, prenom = demo_names.get(role, ("Demo", "User"))
    return UserMeOut(
        id=None, nom=nom, prenom=prenom,
        email=email, role=role, departement="", created_at=None,
        profile_picture=None,
    )


@router.get(
    "/me",
    response_model=UserMeOut,
    summary="Profil de l'utilisateur connecté",
)
async def get_me(
    current_user: dict = Depends(get_current_user),
):
    from src.storage.documents.service_bridge import _NOT_FOUND, get_user_by_email_mongo

    email = current_user.get("email")
    if not email:
        return _demo_me(current_user.get("role", ""), "")

    mongo_user = await get_user_by_email_mongo(email)
    if mongo_user is _NOT_FOUND:
        return _demo_me(current_user.get("role", ""), email)
    if mongo_user is None:
        # Users are written Mongo-only (see CLAUDE.md) — the old SQLite
        # fallback here could only ever serve permanently stale data.
        _log.warning("get_me: MongoDB indisponible — %s introuvable.", email)
        return _demo_me(current_user.get("role", ""), email)
    return _build_me(mongo_user)


@router.patch(
    "/me",
    response_model=UserMeOut,
    summary="Modifier son profil",
    responses={400: {"description": "Non disponible pour les comptes démo"}},
)
async def update_me(
    body: UserMeUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    from src.storage.documents.service_bridge import update_user_profile_native

    email = current_user.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Modification non disponible pour les comptes de démonstration.")

    user = await update_user_profile_native(email, body.nom, body.prenom, body.departement)
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé.")
    return _build_me(user)


@router.patch(
    "/me/avatar",
    response_model=UserMeOut,
    summary="Mettre à jour la photo de profil",
    description=(
        "Reçoit une image encodée en base64 (format data URI complet : "
        "`data:image/jpeg;base64,...`). Taille maximale après décodage : 2 Mo. "
        "Non disponible pour les comptes démo. Limité à 10 requêtes par minute."
    ),
    responses={
        400: {"description": "Format d'image invalide"},
        413: {"description": "Image trop grande (max 2 Mo)"},
        429: {"description": "Trop de tentatives — réessayer dans 60 secondes"},
    },
)
@limiter.limit(limit("10/minute"))
async def update_avatar(
    request: Request,
    body: AvatarUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    from src.storage.documents.service_bridge import update_user_avatar_native

    email = current_user.get("email")
    if not email:
        raise HTTPException(400, "Modification non disponible pour les comptes de démonstration.")

    avatar = body.avatar.strip()

    # Validation du format data URI
    if not avatar.startswith("data:image/"):
        raise HTTPException(400, "Format invalide : la chaîne doit commencer par data:image/.")

    # Garde-fou sur la longueur brute avant décodage
    if len(avatar) > _AVATAR_MAX_STR:
        raise HTTPException(413, "Image trop grande. Limite : 2 Mo après décodage.")

    # Validation de la taille décodée
    try:
        _, b64_part = avatar.split(",", 1)
        # base64.b64decode est tolérant au padding manquant avec validate=False
        decoded_size = len(base64.b64decode(b64_part + "=="))
    except Exception:
        raise HTTPException(400, "Impossible de décoder la chaîne base64.")

    if decoded_size > _AVATAR_MAX_BYTES:
        raise HTTPException(
            413,
            f"Image trop grande ({decoded_size // 1024} Ko). Limite : 2 Mo.",
        )

    user = await update_user_avatar_native(email, avatar)
    if not user:
        raise HTTPException(404, "Utilisateur non trouvé.")

    _log.info("Photo de profil mise à jour pour %s (%d Ko).", email, decoded_size // 1024)
    return _build_me(user)
