"""Risk management endpoints."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session

from api.auth import require_role
from api.deps import get_session

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


def _log_audit(session: Session, user: dict, action: str, resource_id: str, detail: str = "") -> None:
    try:
        from src.storage.orm_models_audit import AuditLogORM
        log = AuditLogORM(
            user_id=user.get("sub", ""),
            user_email=user.get("email", ""),
            user_role=user.get("role", ""),
            action=action,
            resource_type="RISK",
            resource_id=resource_id,
            entity_id=resource_id,
            status="SUCCESS",
            detail=detail,
        )
        session.add(log)
    except Exception:
        pass


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
def create_risk(
    body: RisqueCreateRequest,
    user: dict = _EDIT,
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_roadmap import RisqueORM
    from src.services.risk_service import calculate_criticite

    criticite = calculate_criticite(body.probabilite, body.impact)
    r = RisqueORM(
        titre=body.titre,
        description=body.description,
        type_risque=body.type_risque,
        probabilite=body.probabilite,
        impact=body.impact,
        niveau_criticite=criticite,
        statut=body.statut,
        plan_mitigation=body.plan_mitigation,
        responsable_id=body.responsable_id,
        date_identification=body.date_identification,
        date_echeance_mitigation=body.date_echeance_mitigation,
        feuille_route_id=UUID(body.feuille_route_id) if body.feuille_route_id else None,
        projet_id=body.projet_id,
        created_by=user.get("email", ""),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(r)
    session.flush()
    _log_audit(session, user, "RISK_CREATED", str(r.id), f"Risque créé: {r.titre}")
    session.commit()
    session.refresh(r)
    return _to_out(r)


@router.patch("/{risk_id}", response_model=RisqueOut)
def update_risk(
    risk_id: str,
    body: RisqueUpdateRequest,
    user: dict = _EDIT,
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_roadmap import RisqueORM
    from src.services.risk_service import calculate_criticite

    r = session.get(RisqueORM, UUID(risk_id))
    if not r:
        raise HTTPException(status_code=404, detail="Risque non trouvé.")

    old_statut = r.statut
    recompute = False

    if body.titre is not None:         r.titre = body.titre
    if body.description is not None:   r.description = body.description
    if body.type_risque is not None:   r.type_risque = body.type_risque
    if body.plan_mitigation is not None: r.plan_mitigation = body.plan_mitigation
    if body.responsable_id is not None: r.responsable_id = body.responsable_id
    if body.date_echeance_mitigation is not None: r.date_echeance_mitigation = body.date_echeance_mitigation
    if body.probabilite is not None:
        r.probabilite = body.probabilite
        recompute = True
    if body.impact is not None:
        r.impact = body.impact
        recompute = True
    if body.statut is not None:
        r.statut = body.statut
        if body.statut == "CLOTURE" and not r.date_cloture:
            r.date_cloture = date.today()

    if recompute:
        r.niveau_criticite = calculate_criticite(r.probabilite, r.impact)

    r.updated_at = datetime.now(timezone.utc)

    if body.statut and body.statut != old_statut:
        _log_audit(session, user, "RISK_STATUS_CHANGED", risk_id,
                   f"{old_statut} → {body.statut}")
    elif body.plan_mitigation is not None:
        _log_audit(session, user, "RISK_MITIGATION_UPDATED", risk_id, r.titre)
    if body.statut == "CLOTURE":
        _log_audit(session, user, "RISK_CLOSED", risk_id, r.titre)

    session.commit()
    session.refresh(r)
    return _to_out(r)


@router.delete("/{risk_id}", status_code=status.HTTP_204_NO_CONTENT)
def close_risk(
    risk_id: str,
    user: dict = _EDIT,
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_roadmap import RisqueORM

    r = session.get(RisqueORM, UUID(risk_id))
    if not r:
        raise HTTPException(status_code=404, detail="Risque non trouvé.")
    r.statut = "CLOTURE"
    r.date_cloture = date.today()
    r.updated_at = datetime.now(timezone.utc)
    _log_audit(session, user, "RISK_CLOSED", risk_id, r.titre)
    session.commit()
