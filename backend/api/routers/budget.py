"""Budget vs actual endpoints — read + editable plan."""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.auth import require_role
from api.deps import get_session, get_budget_plan
from api.schemas import (
    BudgetSummaryOut, BudgetLineOut,
    BudgetPlanEntryOut, BudgetPlanEntryIn, BudgetPlanUpdateIn,
)
from src.budget.budget_tracker import BudgetPlan, BudgetTracker

router = APIRouter(prefix="/budget", tags=["budget"])

_log = logging.getLogger(__name__)

_YAML_PATH = Path("config/budget_plan.yaml")

_COMPTABLE_OR_ADMIN = Depends(require_role("Comptable", "Admin"))


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
async def budget_summary(
    year: int = date.today().year,
    month: int = date.today().month,
    session: Session = Depends(get_session),
    plan: BudgetPlan = Depends(get_budget_plan),
):
    from src.storage.documents.service_bridge import budget_summary_mongo

    mongo_result = await budget_summary_mongo(plan, year, month)
    if mongo_result is not None:
        summary = mongo_result["summary"]
        variances = mongo_result["variances"]
    else:
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
async def get_budget_plan_entries(year: int = date.today().year):
    from src.storage.documents.service_bridge import (
        get_budget_plan_entries_mongo, seed_budget_plan_from_yaml_native,
    )

    await seed_budget_plan_from_yaml_native(year, _YAML_PATH)

    mongo_rows = await get_budget_plan_entries_mongo(year)
    if mongo_rows is None:
        # Budget plan entries are written Mongo-only (see CLAUDE.md) — the old
        # SQLite fallback here could only ever serve permanently stale data.
        _log.warning(
            "get_budget_plan_entries: MongoDB indisponible — retour d'une liste vide "
            "(year=%s).", year,
        )
        return []
    return [
        BudgetPlanEntryOut(
            catalog_id=r.catalog_id, year=r.year, label=r.label,
            monthly=r.monthly, note=r.note, annual_total=sum(r.monthly),
        )
        for r in mongo_rows
    ]


@router.put("/plan/{catalog_id}", response_model=BudgetPlanEntryOut, summary="Modifier une ligne budgétaire")
async def update_budget_plan_entry(
    catalog_id: str,
    body: BudgetPlanUpdateIn,
    year: int = date.today().year,
    current_user: dict = _COMPTABLE_OR_ADMIN,
):
    if body.monthly is not None and len(body.monthly) != 12:
        raise HTTPException(status_code=422, detail="monthly must have exactly 12 values")

    from src.storage.documents.service_bridge import update_budget_plan_entry_native

    row = await update_budget_plan_entry_native(catalog_id, year, body, current_user)
    if not row:
        raise HTTPException(status_code=404, detail=f"Budget line '{catalog_id}' not found for year {year}")
    return BudgetPlanEntryOut(
        catalog_id=row.catalog_id, year=row.year, label=row.label,
        monthly=row.monthly, note=row.note, annual_total=sum(row.monthly),
    )


@router.post("/plan", response_model=BudgetPlanEntryOut, status_code=201, summary="Ajouter une ligne budgétaire")
async def create_budget_plan_entry(
    body: BudgetPlanEntryIn,
    year: int = date.today().year,
    current_user: dict = _COMPTABLE_OR_ADMIN,
):
    if len(body.monthly) != 12:
        raise HTTPException(status_code=422, detail="monthly must have exactly 12 values")

    from src.storage.documents.service_bridge import BudgetPlanConflict, create_budget_plan_entry_native

    try:
        row = await create_budget_plan_entry_native(body, year, current_user)
    except BudgetPlanConflict:
        raise HTTPException(status_code=409, detail=f"Budget line '{body.catalog_id}' already exists for year {year}")
    return BudgetPlanEntryOut(
        catalog_id=row.catalog_id, year=row.year, label=row.label,
        monthly=row.monthly, note=row.note, annual_total=sum(row.monthly),
    )


@router.delete("/plan/{catalog_id}", status_code=204, summary="Supprimer une ligne budgétaire")
async def delete_budget_plan_entry(
    catalog_id: str,
    year: int = date.today().year,
    current_user: dict = _COMPTABLE_OR_ADMIN,
):
    from src.storage.documents.service_bridge import delete_budget_plan_entry_native

    found = await delete_budget_plan_entry_native(catalog_id, year, current_user)
    if not found:
        raise HTTPException(status_code=404, detail=f"Budget line '{catalog_id}' not found")
