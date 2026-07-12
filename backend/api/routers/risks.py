"""Risk management endpoints."""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, model_validator

from api.auth import require_role

router = APIRouter(prefix="/risks", tags=["risks"])

_log = logging.getLogger(__name__)

_EDIT = Depends(require_role("Chef de Projet", "Admin", "Direction"))
_VIEW = Depends(require_role("Chef de Projet", "Admin", "Direction", "Comptable"))

_VALID_TYPE_RISQUE = {"DELAI", "BUDGET", "TECHNIQUE", "RESSOURCE", "FOURNISSEUR", "REGLEMENTAIRE", "AUTRE"}
_VALID_PROBABILITE = {"FAIBLE", "MOYENNE", "ELEVEE"}
_VALID_IMPACT = {"FAIBLE", "MOYEN", "ELEVE", "CRITIQUE"}
_VALID_STATUT = {"IDENTIFIE", "EN_SURVEILLANCE", "EN_TRAITEMENT", "MAITRISE", "SURVENU", "CLOTURE"}


class RisqueOut(BaseModel):
    id: str
    titre: str
    description: str
    type_risque: str
    probabilite: str
    impact: str
    niveau_criticite: str
    statut: str
    plan_mitigation: str
    responsable_id: str | None
    date_identification: str
    date_echeance_mitigation: str | None
    date_cloture: str | None
    feuille_route_id: str | None
    projet_id: str | None
    created_by: str
    created_at: str
    updated_at: str


class RisqueCreateRequest(BaseModel):
    titre: str
    description: str = ""
    type_risque: str = "AUTRE"
    probabilite: str
    impact: str
    statut: str = "IDENTIFIE"
    plan_mitigation: str = ""
    responsable_id: str | None = None
    date_identification: date
    date_echeance_mitigation: date | None = None
    feuille_route_id: str | None = None
    projet_id: str | None = None

    @model_validator(mode="after")
    def _check_parent(self) -> "RisqueCreateRequest":
        if not self.feuille_route_id and not self.projet_id:
            raise ValueError("Au moins un de feuille_route_id ou projet_id doit être défini.")
        return self


class RisqueUpdateRequest(BaseModel):
    titre: str | None = None
    description: str | None = None
    type_risque: str | None = None
    probabilite: str | None = None
    impact: str | None = None
    statut: str | None = None
    plan_mitigation: str | None = None
    responsable_id: str | None = None
    date_echeance_mitigation: date | None = None


def _to_out(r) -> RisqueOut:
    return RisqueOut(
        id=str(r.id),
        titre=r.titre,
        description=r.description,
        type_risque=r.type_risque,
        probabilite=r.probabilite,
        impact=r.impact,
        niveau_criticite=r.niveau_criticite,
        statut=r.statut,
        plan_mitigation=r.plan_mitigation,
        responsable_id=r.responsable_id,
        date_identification=r.date_identification.isoformat(),
        date_echeance_mitigation=r.date_echeance_mitigation.isoformat() if r.date_echeance_mitigation else None,
        date_cloture=r.date_cloture.isoformat() if r.date_cloture else None,
        feuille_route_id=str(r.feuille_route_id) if r.feuille_route_id else None,
        projet_id=r.projet_id,
        created_by=r.created_by,
        created_at=r.created_at.isoformat(),
        updated_at=r.updated_at.isoformat(),
    )


@router.get("", response_model=list[RisqueOut])
async def list_risks(
    projet_id: str | None = Query(None),
    feuille_route_id: str | None = Query(None),
    statut: str | None = Query(None),
    niveau_criticite: str | None = Query(None),
):
    from src.storage.documents.service_bridge import list_risks_mongo

    mongo_result = await list_risks_mongo(projet_id, feuille_route_id, statut, niveau_criticite)
    if mongo_result is None:
        # Risks are written Mongo-only (see CLAUDE.md) — the old SQLite
        # fallback here could only ever serve permanently stale data.
        _log.warning("list_risks: MongoDB indisponible — retour d'une liste vide.")
        return []
    return [_to_out(r) for r in mongo_result]


@router.get("/summary")
async def risk_summary():
    from src.storage.documents.service_bridge import risk_summary_mongo

    mongo_result = await risk_summary_mongo()
    if mongo_result is None:
        _log.warning("risk_summary: MongoDB indisponible — retour d'un résumé vide.")
        return {
            "by_criticite": {"FAIBLE": 0, "MOYENNE": 0, "ELEVEE": 0, "CRITIQUE": 0},
            "by_statut": {}, "overdue": [], "top_critical": [], "total_active": 0,
        }
    return mongo_result


@router.get("/par-projet", summary="Risques groupés par projet")
async def risks_par_projet(_: None = _VIEW):
    """Pour chaque projet ayant au moins un risque : nom du projet, comptes
    par criticité et liste complète. Filtrage statut/criticité côté client.
    Projets triés par criticité maximale décroissante."""
    from src.storage.documents.service_bridge import risks_par_projet_mongo

    mongo_result = await risks_par_projet_mongo()
    if mongo_result is None:
        _log.warning("risks_par_projet: MongoDB indisponible — retour d'une liste vide.")
        return []
    return [
        {**g, "risks": [_to_out(r) for r in g["risks"]]}
        for g in mongo_result
    ]


@router.get("/roadmap/{feuille_route_id}", response_model=list[RisqueOut])
async def risks_for_roadmap(feuille_route_id: str):
    from src.storage.documents.service_bridge import risks_for_roadmap_mongo

    mongo_result = await risks_for_roadmap_mongo(feuille_route_id)
    if mongo_result is None:
        _log.warning(
            "risks_for_roadmap: MongoDB indisponible — retour d'une liste vide "
            "(feuille_route_id=%s).", feuille_route_id,
        )
        return []
    return [_to_out(r) for r in mongo_result]


@router.get("/projet/{projet_id}", response_model=list[RisqueOut])
async def risks_for_project(projet_id: str):
    from src.storage.documents.service_bridge import risks_for_project_mongo

    mongo_result = await risks_for_project_mongo(projet_id)
    if mongo_result is None:
        _log.warning(
            "risks_for_project: MongoDB indisponible — retour d'une liste vide "
            "(projet_id=%s).", projet_id,
        )
        return []
    return [_to_out(r) for r in mongo_result]


@router.post("", response_model=RisqueOut, status_code=status.HTTP_201_CREATED)
async def create_risk(
    body: RisqueCreateRequest,
    user: dict = _EDIT,
):
    from src.storage.documents.service_bridge import create_risk_native

    r = await create_risk_native(body, user)
    return _to_out(r)


@router.patch("/{risk_id}", response_model=RisqueOut)
async def update_risk(
    risk_id: str,
    body: RisqueUpdateRequest,
    user: dict = _EDIT,
):
    from src.storage.documents.service_bridge import update_risk_native

    r = await update_risk_native(risk_id, body, user)
    if not r:
        raise HTTPException(status_code=404, detail="Risque non trouvé.")
    return _to_out(r)


@router.delete("/{risk_id}", status_code=status.HTTP_204_NO_CONTENT)
async def close_risk(
    risk_id: str,
    user: dict = _EDIT,
):
    from src.storage.documents.service_bridge import close_risk_native

    r = await close_risk_native(risk_id, user)
    if not r:
        raise HTTPException(status_code=404, detail="Risque non trouvé.")
