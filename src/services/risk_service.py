"""Risk management service — matrix logic and DB queries."""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

# Risk matrix: (probabilite, impact) → niveau_criticite
_MATRIX: dict[tuple[str, str], str] = {
    ("FAIBLE",  "FAIBLE"):   "FAIBLE",
    ("FAIBLE",  "MOYEN"):    "FAIBLE",
    ("FAIBLE",  "ELEVE"):    "MOYENNE",
    ("FAIBLE",  "CRITIQUE"): "MOYENNE",
    ("MOYENNE", "FAIBLE"):   "FAIBLE",
    ("MOYENNE", "MOYEN"):    "MOYENNE",
    ("MOYENNE", "ELEVE"):    "ELEVEE",
    ("MOYENNE", "CRITIQUE"): "ELEVEE",
    ("ELEVEE",  "FAIBLE"):   "MOYENNE",
    ("ELEVEE",  "MOYEN"):    "ELEVEE",
    ("ELEVEE",  "ELEVE"):    "ELEVEE",
    ("ELEVEE",  "CRITIQUE"): "CRITIQUE",
}

_CRITICITE_ORDER = {"FAIBLE": 0, "MOYENNE": 1, "ELEVEE": 2, "CRITIQUE": 3}


def calculate_criticite(probabilite: str, impact: str) -> str:
    return _MATRIX.get((probabilite, impact), "MOYENNE")


def get_risks_for_roadmap_item(db: Session, feuille_route_id: UUID) -> list:
    from src.storage.orm_models_extra import RisqueORM
    return (
        db.query(RisqueORM)
        .filter(RisqueORM.feuille_route_id == feuille_route_id)
        .filter(RisqueORM.statut != "CLOTURE")
        .order_by(RisqueORM.created_at.desc())
        .all()
    )


def get_risks_for_project(db: Session, projet_id: str) -> list:
    from src.storage.orm_models_extra import RisqueORM
    return (
        db.query(RisqueORM)
        .filter(RisqueORM.projet_id == projet_id)
        .filter(RisqueORM.statut != "CLOTURE")
        .order_by(RisqueORM.created_at.desc())
        .all()
    )


def get_risk_summary(db: Session) -> dict:
    from src.storage.orm_models_extra import RisqueORM

    all_risks = db.query(RisqueORM).all()
    today = date.today()

    by_criticite: dict[str, int] = {"FAIBLE": 0, "MOYENNE": 0, "ELEVEE": 0, "CRITIQUE": 0}
    by_statut: dict[str, int] = {}
    overdue: list[dict] = []

    for r in all_risks:
        if r.statut != "CLOTURE":
            by_criticite[r.niveau_criticite] = by_criticite.get(r.niveau_criticite, 0) + 1
        by_statut[r.statut] = by_statut.get(r.statut, 0) + 1
        if (
            r.statut not in ("CLOTURE", "MAITRISE")
            and r.date_echeance_mitigation
            and r.date_echeance_mitigation < today
        ):
            overdue.append({"id": str(r.id), "titre": r.titre, "date_echeance_mitigation": r.date_echeance_mitigation.isoformat()})

    top_critical = sorted(
        [r for r in all_risks if r.niveau_criticite == "CRITIQUE" and r.statut not in ("CLOTURE", "MAITRISE")],
        key=lambda r: r.created_at,
        reverse=True,
    )[:5]

    return {
        "by_criticite": by_criticite,
        "by_statut": by_statut,
        "overdue": overdue,
        "top_critical": [
            {"id": str(r.id), "titre": r.titre, "statut": r.statut, "projet_id": r.projet_id}
            for r in top_critical
        ],
        "total_active": sum(by_criticite.values()),
    }
