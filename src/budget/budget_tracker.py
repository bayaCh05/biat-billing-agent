"""Budget tracker — planned vs actual analysis.

Loads the annual budget from config/budget_plan.yaml and compares it
against actual spending extracted from validated supplier invoices in the DB.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from src.utils.date_utils import last_day_of_month as _last_day

import yaml
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, func

from src.storage.orm_models import InvoiceORM


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class BudgetLine:
    catalog_id: str
    label: str
    monthly_budget: list[float]          # 12 values, index 0 = January

    @property
    def annual_budget(self) -> float:
        return sum(self.monthly_budget)

    def budget_for_month(self, month: int) -> float:
        """month: 1-12"""
        return self.monthly_budget[month - 1]

    def budget_ytd(self, through_month: int) -> float:
        """Cumulative budget from January through through_month (1-12)."""
        return sum(self.monthly_budget[:through_month])


@dataclass
class MonthlyVariance:
    catalog_id: str
    label: str
    year: int
    month: int                           # 1-12
    budget: float
    actual: float

    @property
    def variance(self) -> float:
        return self.actual - self.budget

    @property
    def variance_pct(self) -> float:
        if self.budget == 0:
            return 0.0 if self.actual == 0 else float("inf")
        return round((self.variance / self.budget) * 100, 2)

    @property
    def is_over(self) -> bool:
        return self.variance > 0

    @property
    def status(self) -> str:
        if self.budget == 0 and self.actual == 0:
            return "on_budget"
        pct = abs(self.variance_pct)
        if pct <= 5:
            return "on_budget"
        elif pct <= 15:
            return "warning"
        else:
            return "over" if self.is_over else "under"


@dataclass
class YearVariance:
    """Aggregated variance for a full year or YTD."""
    catalog_id: str
    label: str
    year: int
    through_month: int                   # last month included
    budget_ytd: float
    actual_ytd: float
    monthly: list[MonthlyVariance] = field(default_factory=list)

    @property
    def variance_ytd(self) -> float:
        return self.actual_ytd - self.budget_ytd

    @property
    def variance_pct_ytd(self) -> float:
        if self.budget_ytd == 0:
            return 0.0 if self.actual_ytd == 0 else float("inf")
        return round((self.variance_ytd / self.budget_ytd) * 100, 2)

    @property
    def status(self) -> str:
        pct = abs(self.variance_pct_ytd)
        if pct <= 5:
            return "on_budget"
        elif pct <= 15:
            return "warning"
        else:
            return "over" if self.variance_ytd > 0 else "under"


# ── Budget plan loader ────────────────────────────────────────────────────────

class BudgetPlan:
    def __init__(self, lines: list[BudgetLine], exercise: int, currency: str = "TND") -> None:
        self.lines = lines
        self.exercise = exercise
        self.currency = currency
        self._by_id: dict[str, BudgetLine] = {ln.catalog_id: ln for ln in lines}

    @classmethod
    def from_yaml(cls, path: str | Path) -> "BudgetPlan":
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        exercise = int(raw.get("exercise", date.today().year))
        currency = raw.get("currency", "TND")
        lines: list[BudgetLine] = []

        for entry in raw.get("entries", []):
            monthly_raw = entry["monthly"]
            if isinstance(monthly_raw, (int, float)):
                monthly = [float(monthly_raw)] * 12
            else:
                monthly = [float(v) for v in monthly_raw]
                if len(monthly) != 12:
                    raise ValueError(
                        f"Budget entry '{entry['catalog_id']}' must have exactly 12 monthly values, "
                        f"got {len(monthly)}"
                    )
            lines.append(BudgetLine(
                catalog_id=entry["catalog_id"],
                label=entry.get("label", entry["catalog_id"]),
                monthly_budget=monthly,
            ))

        return cls(lines, exercise, currency)

    def get(self, catalog_id: str) -> Optional[BudgetLine]:
        return self._by_id.get(catalog_id)

    def total_annual_budget(self) -> float:
        return sum(ln.annual_budget for ln in self.lines)

    def total_monthly_budget(self, month: int) -> float:
        return sum(ln.budget_for_month(month) for ln in self.lines)


# ── Budget tracker ────────────────────────────────────────────────────────────

class BudgetTracker:
    """Compares planned budget against actual invoice amounts from the DB.

    Actual spending is read from validated supplier invoices (VALIDATED, EXPORTED,
    PAID statuses) grouped by cost_catalog_id and invoice month.
    """

    ACTUAL_STATUSES = ("VALIDATED", "EXPORTED", "PAID")

    def __init__(self, plan: BudgetPlan, session: Session) -> None:
        self.plan = plan
        self.session = session

    # ── Public API ────────────────────────────────────────────────────────────

    def monthly_variance(self, year: int, month: int) -> list[MonthlyVariance]:
        """Variance for every catalog line for a given month."""
        actuals = self._actuals_by_catalog(year, month, month)
        result: list[MonthlyVariance] = []
        for line in self.plan.lines:
            actual = actuals.get(line.catalog_id, 0.0)
            result.append(MonthlyVariance(
                catalog_id=line.catalog_id,
                label=line.label,
                year=year,
                month=month,
                budget=line.budget_for_month(month),
                actual=actual,
            ))
        return result

    def ytd_variance(self, year: int, through_month: int) -> list[YearVariance]:
        """YTD variance for every catalog line from January through through_month."""
        actuals_by_month: dict[int, dict[str, float]] = {}
        for m in range(1, through_month + 1):
            actuals_by_month[m] = self._actuals_by_catalog(year, m, m)

        result: list[YearVariance] = []
        for line in self.plan.lines:
            monthly_variances = [
                MonthlyVariance(
                    catalog_id=line.catalog_id,
                    label=line.label,
                    year=year,
                    month=m,
                    budget=line.budget_for_month(m),
                    actual=actuals_by_month[m].get(line.catalog_id, 0.0),
                )
                for m in range(1, through_month + 1)
            ]
            result.append(YearVariance(
                catalog_id=line.catalog_id,
                label=line.label,
                year=year,
                through_month=through_month,
                budget_ytd=line.budget_ytd(through_month),
                actual_ytd=sum(mv.actual for mv in monthly_variances),
                monthly=monthly_variances,
            ))
        return result

    def summary(self, year: int, through_month: int) -> dict:
        """High-level budget summary for dashboard KPIs."""
        ytd = self.ytd_variance(year, through_month)
        total_budget = sum(yv.budget_ytd for yv in ytd)
        total_actual = sum(yv.actual_ytd for yv in ytd)
        over_lines = [yv for yv in ytd if yv.status == "over"]
        warning_lines = [yv for yv in ytd if yv.status == "warning"]
        return {
            "year": year,
            "through_month": through_month,
            "total_budget_ytd": round(total_budget, 2),
            "total_actual_ytd": round(total_actual, 2),
            "total_variance_ytd": round(total_actual - total_budget, 2),
            "variance_pct": round(
                ((total_actual - total_budget) / total_budget * 100) if total_budget else 0, 2
            ),
            "lines_over_budget": len(over_lines),
            "lines_warning": len(warning_lines),
            "top_overruns": sorted(over_lines, key=lambda yv: yv.variance_ytd, reverse=True)[:5],
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _actuals_by_catalog(
        self, year: int, from_month: int, to_month: int
    ) -> dict[str, float]:
        """Sum of amount_ht per cost_catalog_id for validated invoices in the date range."""
        start = date(year, from_month, 1)
        end = _last_day(year, to_month)

        rows = self.session.execute(
            select(
                InvoiceORM.cost_catalog_id,
                func.sum(InvoiceORM.amount_ht).label("total"),
            )
            .where(
                and_(
                    InvoiceORM.status.in_(self.ACTUAL_STATUSES),
                    InvoiceORM.direction == "fournisseur",
                    InvoiceORM.invoice_date >= start,
                    InvoiceORM.invoice_date <= end,
                    InvoiceORM.cost_catalog_id.isnot(None),
                    InvoiceORM.amount_ht.isnot(None),
                )
            )
            .group_by(InvoiceORM.cost_catalog_id)
        ).all()

        return {row.cost_catalog_id: float(row.total or 0) for row in rows}


