"""Budget vs actual endpoints — read + editable plan."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import require_role
from api.deps import get_session, get_budget_plan
from api.schemas import (
    BudgetSummaryOut, BudgetLineOut,
    BudgetPlanEntryOut, BudgetPlanEntryIn, BudgetPlanUpdateIn,
)
from src.budget.budget_tracker import BudgetPlan, BudgetTracker
from src.storage.orm_models import BudgetPlanORM

router = APIRouter(prefix="/budget", tags=["budget"])

_YAML_PATH = Path("config/budget_plan.yaml")

_COMPTABLE_OR_ADMIN = Depends(require_role("Comptable", "Admin"))


def _seed_from_yaml(session: Session, year: int) -> None:
    """Populate budget_plan_entries from YAML if the table is empty for that year."""
    existing = session.execute(
        select(BudgetPlanORM).where(BudgetPlanORM.year == year).limit(1)
    ).scalar_one_or_none()
    if existing:
        return
    data = yaml.safe_load(_YAML_PATH.read_text())
    for entry in data.get("entries", []):
        session.add(BudgetPlanORM(
            catalog_id=entry["catalog_id"],
            year=year,
            label=entry["label"],
            monthly=[float(v) for v in entry["monthly"]],
            note=entry.get("note"),
        ))
    session.commit()


@router.get(
    "/summary",
    response_model=BudgetSummaryOut,
    summary="Synthèse budgétaire annuelle",
    description=(
        "Retourne le suivi budget vs réel pour l'année en cours ou une année spécifiée. "
        "Le calcul est cumulatif jusqu'au mois `month` (YTD — Year to Date). "
        "Inclut la variance en pourcentage et le détail par ligne de catalogue PCE."
    ),
    response_description="Synthèse avec totaux YTD, variance et liste des lignes en dépassement",
)
def budget_summary(
    year: int = date.today().year,
    month: int = date.today().month,
    session: Session = Depends(get_session),
    plan: BudgetPlan = Depends(get_budget_plan),
):
    tracker = BudgetTracker(plan=plan, session=session)
    summary = tracker.summary(year=year, through_month=month)

    variances = tracker.ytd_variance(year=year, through_month=month)

    lines = []
    for v in variances:
        lines.append(BudgetLineOut(
            catalog_id=v.catalog_id,
            label=v.label,
            budget_ytd=v.budget_ytd,
            actual_ytd=v.actual_ytd,
            variance=v.variance_ytd,
            variance_pct=v.variance_pct_ytd,
            is_over=v.variance_ytd > 0,
        ))

    return BudgetSummaryOut(
        year=year,
        through_month=month,
        total_budget_ytd=summary["total_budget_ytd"],
        total_actual_ytd=summary["total_actual_ytd"],
        variance_pct=summary["variance_pct"],
        lines_over_budget=summary["lines_over_budget"],
        lines=lines,
    )


# ── Editable plan CRUD ────────────────────────────────────────────────────────

@router.get("/plan", response_model=list[BudgetPlanEntryOut], summary="Plan budgétaire éditable")
def get_budget_plan_entries(year: int = date.today().year, session: Session = Depends(get_session)):
    _seed_from_yaml(session, year)
    rows = session.execute(
        select(BudgetPlanORM).where(BudgetPlanORM.year == year).order_by(BudgetPlanORM.catalog_id)
    ).scalars().all()
    return [
        BudgetPlanEntryOut(
            catalog_id=r.catalog_id, year=r.year, label=r.label,
            monthly=r.monthly, note=r.note,
            annual_total=sum(r.monthly),
        )
        for r in rows
    ]


@router.put("/plan/{catalog_id}", response_model=BudgetPlanEntryOut, summary="Modifier une ligne budgétaire")
def update_budget_plan_entry(
    catalog_id: str,
    body: BudgetPlanUpdateIn,
    year: int = date.today().year,
    _: None = _COMPTABLE_OR_ADMIN,
    session: Session = Depends(get_session),
):
    row = session.execute(
        select(BudgetPlanORM).where(
            BudgetPlanORM.catalog_id == catalog_id,
            BudgetPlanORM.year == year,
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail=f"Budget line '{catalog_id}' not found for year {year}")
    if body.label is not None:
        row.label = body.label
    if body.monthly is not None:
        if len(body.monthly) != 12:
            raise HTTPException(status_code=422, detail="monthly must have exactly 12 values")
        row.monthly = [float(v) for v in body.monthly]
    if body.note is not None:
        row.note = body.note
    row.updated_at = datetime.now(timezone.utc)
    session.commit()
    return BudgetPlanEntryOut(
        catalog_id=row.catalog_id, year=row.year, label=row.label,
        monthly=row.monthly, note=row.note, annual_total=sum(row.monthly),
    )


@router.post("/plan", response_model=BudgetPlanEntryOut, status_code=201, summary="Ajouter une ligne budgétaire")
def create_budget_plan_entry(
    body: BudgetPlanEntryIn,
    year: int = date.today().year,
    _: None = _COMPTABLE_OR_ADMIN,
    session: Session = Depends(get_session),
):
    if len(body.monthly) != 12:
        raise HTTPException(status_code=422, detail="monthly must have exactly 12 values")
    existing = session.execute(
        select(BudgetPlanORM).where(
            BudgetPlanORM.catalog_id == body.catalog_id,
            BudgetPlanORM.year == year,
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"Budget line '{body.catalog_id}' already exists for year {year}")
    row = BudgetPlanORM(
        catalog_id=body.catalog_id, year=year, label=body.label,
        monthly=[float(v) for v in body.monthly], note=body.note,
    )
    session.add(row)
    session.commit()
    return BudgetPlanEntryOut(
        catalog_id=row.catalog_id, year=row.year, label=row.label,
        monthly=row.monthly, note=row.note, annual_total=sum(row.monthly),
    )


@router.delete("/plan/{catalog_id}", status_code=204, summary="Supprimer une ligne budgétaire")
def delete_budget_plan_entry(
    catalog_id: str,
    year: int = date.today().year,
    _: None = _COMPTABLE_OR_ADMIN,
    session: Session = Depends(get_session),
):
    row = session.execute(
        select(BudgetPlanORM).where(
            BudgetPlanORM.catalog_id == catalog_id,
            BudgetPlanORM.year == year,
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail=f"Budget line '{catalog_id}' not found")
    session.delete(row)
    session.commit()
