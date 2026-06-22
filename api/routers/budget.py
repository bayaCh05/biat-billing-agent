"""Budget vs actual endpoints."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import get_session, get_budget_plan
from api.schemas import BudgetSummaryOut, BudgetLineOut
from src.budget.budget_tracker import BudgetPlan, BudgetTracker

router = APIRouter(prefix="/budget", tags=["budget"])


@router.get("/summary", response_model=BudgetSummaryOut)
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
