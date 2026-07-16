"""Budget domain types — plan config (YAML) and variance value objects.

MonthlyVariance/YearVariance are pure dataclasses with no storage dependency —
used by both the (deleted) SQLAlchemy BudgetTracker's successor and the
Mongo-native src.storage.documents.service_bridge.budget_summary_mongo().
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import yaml


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
