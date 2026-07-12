"""Livrables and phase validation endpoints."""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.auth import get_current_user, require_role

router = APIRouter(tags=["projects"])

_log = logging.getLogger(__name__)

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


@router.get(
    "/phases/{phase_id}/livrables",
    response_model=list[LivrableOut],
    summary="Livrables d'une phase",
    description=(
        "Liste tous les livrables d'une phase de projet, "
        "triés par date de livraison prévue. "
        "Statuts possibles : EN_ATTENTE, EN_COURS, LIVRE, VALIDE."
    ),
    response_description="Liste des livrables avec dates et statuts",
)
async def list_livrables(phase_id: str):
    from src.storage.documents.service_bridge import list_livrables_mongo

    mongo_items = await list_livrables_mongo(phase_id)
    if mongo_items is None:
        # Livrables are written Mongo-only (see CLAUDE.md) — the old SQLite
        # fallback here could only ever serve permanently stale data.
        _log.warning(
            "list_livrables: MongoDB indisponible — retour d'une liste vide "
            "(phase_id=%s).", phase_id,
        )
        return []
    return [_to_out(i) for i in mongo_items]


@router.post(
    "/phases/{phase_id}/livrables",
    response_model=LivrableOut,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un livrable",
    description=(
        "Ajoute un livrable à une phase de projet. "
        "Rôle Chef de Projet ou Admin requis. "
        "L'auteur est enregistré automatiquement depuis le token JWT."
    ),
    response_description="Livrable créé avec son identifiant",
    responses={
        403: {"description": "Rôle Chef de Projet ou Admin requis"},
        404: {"description": "Phase non trouvée"},
    },
)
async def create_livrable(
    phase_id: str,
    body: LivrableCreateRequest,
    current_user: dict = Depends(get_current_user),
    _: dict = _EDIT,
):
    from src.storage.documents.service_bridge import create_livrable_native

    created_by = current_user.get("email", current_user.get("role", ""))
    lv = await create_livrable_native(phase_id, body, created_by)
    if lv is None:
        raise HTTPException(status_code=404, detail="Phase non trouvée.")
    return _to_out(lv)


@router.patch(
    "/livrables/{livrable_id}",
    response_model=LivrableOut,
    summary="Mettre à jour un livrable",
    description="Modifie le titre, la description, le statut ou la date de livraison réelle d'un livrable.",
    response_description="Livrable mis à jour",
    responses={
        403: {"description": "Rôle Chef de Projet ou Admin requis"},
        404: {"description": "Livrable non trouvé"},
    },
)
async def update_livrable(
    livrable_id: str,
    body: LivrableUpdateRequest,
    _: dict = _EDIT,
):
    from src.storage.documents.service_bridge import update_livrable_native

    lv = await update_livrable_native(livrable_id, body)
    if not lv:
        raise HTTPException(status_code=404, detail="Livrable non trouvé.")
    return _to_out(lv)


@router.post(
    "/phases/{phase_id}/valider",
    summary="Valider une phase",
    description=(
        "Clôture une phase si et seulement si tous ses livrables sont au statut LIVRE ou VALIDE. "
        "En cas de livrables non terminés, retourne HTTP 400 avec le nombre de bloquants."
    ),
    response_description="Message de confirmation avec nouveau statut VALIDEE",
    responses={
        400: {"description": "Livrables non terminés — liste des bloquants"},
        403: {"description": "Rôle Chef de Projet ou Admin requis"},
        404: {"description": "Phase non trouvée"},
    },
)
async def valider_phase(
    phase_id: str,
    _: dict = _EDIT,
):
    from src.storage.documents.service_bridge import PhaseValidationError, valider_phase_native

    try:
        phase = await valider_phase_native(phase_id)
    except PhaseValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{exc.count} livrable(s) non terminé(s) — tous doivent être LIVRE ou VALIDE avant validation.",
        )
    if phase is None:
        raise HTTPException(status_code=404, detail="Phase non trouvée.")
    return {"message": f"Phase '{phase.name}' validée avec succès.", "status": "VALIDEE"}
