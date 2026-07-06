"""Risk management endpoints."""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session

from api.auth import require_role
from api.deps import get_session

router = APIRouter(prefix="/risks", tags=["risks"])

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
def list_risks(
    projet_id: str | None = Query(None),
    feuille_route_id: str | None = Query(None),
    statut: str | None = Query(None),
    niveau_criticite: str | None = Query(None),
    session: Session = Depends(get_session),
):
    from src.storage.orm_models_roadmap import RisqueORM
    from sqlalchemy import select

    q = select(RisqueORM)
    if projet_id:
        q = q.where(RisqueORM.projet_id == projet_id)
    if feuille_route_id:
        q = q.where(RisqueORM.feuille_route_id == UUID(feuille_route_id))
    if statut:
        q = q.where(RisqueORM.statut == statut)
    if niveau_criticite:
        q = q.where(RisqueORM.niveau_criticite == niveau_criticite)
    q = q.order_by(RisqueORM.created_at.desc())
    return [_to_out(r) for r in session.execute(q).scalars().all()]


@router.get("/summary")
def risk_summary(session: Session = Depends(get_session)):
    from src.services.risk_service import get_risk_summary
    return get_risk_summary(session)


@router.get("/par-projet", summary="Risques groupés par projet")
def risks_par_projet(
    session: Session = Depends(get_session),
    _: None = _VIEW,
):
    """Pour chaque projet ayant au moins un risque : nom du projet, comptes
    par criticité et liste complète. Filtrage statut/criticité côté client.
    Projets triés par criticité maximale décroissante."""
    from src.storage.orm_models_roadmap import RisqueORM
    from src.storage.orm_models_projects import CharteProjetORM
    from sqlalchemy import select

    # Tous les risques liés à un projet
    risks = session.execute(
        select(RisqueORM)
        .where(RisqueORM.projet_id.isnot(None))
        .order_by(RisqueORM.projet_id, RisqueORM.created_at.desc())
    ).scalars().all()

    # Noms de projets depuis la charte
    chartes = session.execute(select(CharteProjetORM)).scalars().all()
    proj_names: dict[str, str] = {c.project_id: c.project_name for c in chartes}

    grouped: dict[str, list] = {}
    for r in risks:
        grouped.setdefault(r.projet_id, []).append(r)

    result = []
    for projet_id, proj_risks in grouped.items():
        by_criticite: dict[str, int] = {"FAIBLE": 0, "MOYENNE": 0, "ELEVEE": 0, "CRITIQUE": 0}
        for r in proj_risks:
            by_criticite[r.niveau_criticite] = by_criticite.get(r.niveau_criticite, 0) + 1
        result.append({
            "projet_id": projet_id,
            "project_name": proj_names.get(projet_id, projet_id),
            "total": len(proj_risks),
            "by_criticite": by_criticite,
            "risks": [_to_out(r) for r in proj_risks],
        })

    # Projets les plus critiques en premier
    _order = {"CRITIQUE": 3, "ELEVEE": 2, "MOYENNE": 1, "FAIBLE": 0}
    result.sort(
        key=lambda g: max((_order.get(c, 0) * n) for c, n in g["by_criticite"].items()),
        reverse=True,
    )
    return result


@router.get("/roadmap/{feuille_route_id}", response_model=list[RisqueOut])
def risks_for_roadmap(
    feuille_route_id: str,
    session: Session = Depends(get_session),
):
    from src.services.risk_service import get_risks_for_roadmap_item
    return [_to_out(r) for r in get_risks_for_roadmap_item(session, UUID(feuille_route_id))]


@router.get("/projet/{projet_id}", response_model=list[RisqueOut])
def risks_for_project(
    projet_id: str,
    session: Session = Depends(get_session),
):
    from src.services.risk_service import get_risks_for_project
    return [_to_out(r) for r in get_risks_for_project(session, projet_id)]


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
