"""Unit tests for src/budget — BudgetPlan/BudgetLine and variance value objects."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.budget.budget_plan import (
    BudgetLine,
    BudgetPlan,
    MonthlyVariance,
    YearVariance,
)


# ── BudgetLine ────────────────────────────────────────────────────────────────

class TestBudgetLine:
    def _line(self, monthly=None):
        return BudgetLine(
            catalog_id="salaires",
            label="Salaires",
            monthly_budget=monthly or [10000.0] * 12,
        )

    def test_annual_budget(self):
        line = self._line([1000.0] * 12)
        assert line.annual_budget == 12000.0

    def test_budget_for_month(self):
        monthly = list(range(1, 13))
        line = self._line([float(m) for m in monthly])
        assert line.budget_for_month(1) == 1.0
        assert line.budget_for_month(12) == 12.0

    def test_budget_ytd(self):
        line = self._line([1000.0] * 12)
        assert line.budget_ytd(3) == 3000.0
        assert line.budget_ytd(12) == 12000.0

    def test_budget_ytd_uneven(self):
        line = self._line([0, 0, 5000, 0, 0, 5000, 0, 0, 0, 0, 0, 0])
        assert line.budget_ytd(6) == 10000.0


# ── MonthlyVariance ───────────────────────────────────────────────────────────

class TestMonthlyVariance:
    def _mv(self, budget, actual):
        return MonthlyVariance(
            catalog_id="x", label="X", year=2026, month=3,
            budget=budget, actual=actual,
        )

    def test_variance(self):
        assert self._mv(1000, 1200).variance == pytest.approx(200)

    def test_variance_pct(self):
        assert self._mv(1000, 1200).variance_pct == pytest.approx(20.0)

    def test_variance_pct_zero_budget(self):
        mv = self._mv(0, 500)
        assert mv.variance_pct == float("inf")

    def test_variance_pct_both_zero(self):
        assert self._mv(0, 0).variance_pct == 0.0

    def test_status_on_budget(self):
        assert self._mv(1000, 1040).status == "on_budget"  # +4%

    def test_status_warning(self):
        assert self._mv(1000, 1100).status == "warning"    # +10%

    def test_status_over(self):
        assert self._mv(1000, 1200).status == "over"       # +20%

    def test_status_under(self):
        assert self._mv(1000, 800).status == "under"       # -20%

    def test_is_over(self):
        assert self._mv(1000, 1100).is_over is True
        assert self._mv(1000, 900).is_over is False


# ── YearVariance ──────────────────────────────────────────────────────────────

class TestYearVariance:
    def _yv(self, budget_ytd, actual_ytd):
        return YearVariance(
            catalog_id="x", label="X", year=2026, through_month=6,
            budget_ytd=budget_ytd, actual_ytd=actual_ytd,
        )

    def test_variance_ytd(self):
        assert self._yv(6000, 7000).variance_ytd == pytest.approx(1000)

    def test_status_over(self):
        yv = self._yv(6000, 7200)   # +20%
        assert yv.status == "over"

    def test_status_on_budget(self):
        yv = self._yv(6000, 6100)   # +1.7%
        assert yv.status == "on_budget"


# ── BudgetPlan.from_yaml ──────────────────────────────────────────────────────

SAMPLE_YAML = """
exercise: 2026
currency: TND
entries:
  - catalog_id: salaires
    label: Salaires et traitements
    monthly: [85000, 85000, 85000, 85000, 85000, 85000, 85000, 85000, 85000, 85000, 85000, 85000]
  - catalog_id: loyers_immobiliers
    label: Loyers immobiliers
    monthly: [12000, 12000, 12000, 12000, 12000, 12000, 12000, 12000, 12000, 12000, 12000, 12000]
  - catalog_id: materiel_informatique
    label: Matériel informatique
    monthly: [0, 0, 25000, 0, 0, 0, 0, 0, 20000, 0, 0, 0]
"""


class TestBudgetPlanFromYaml:
    def _plan(self):
        tmp = Path("/tmp/test_budget_plan.yaml")
        tmp.write_text(SAMPLE_YAML, encoding="utf-8")
        return BudgetPlan.from_yaml(tmp)

    def test_loads_exercise(self):
        plan = self._plan()
        assert plan.exercise == 2026

    def test_loads_all_lines(self):
        plan = self._plan()
        assert len(plan.lines) == 3

    def test_annual_budget_salaires(self):
        plan = self._plan()
        line = plan.get("salaires")
        assert line is not None
        assert line.annual_budget == pytest.approx(85000 * 12)

    def test_uneven_monthly(self):
        plan = self._plan()
        line = plan.get("materiel_informatique")
        assert line.budget_for_month(3) == 25000.0
        assert line.budget_for_month(1) == 0.0

    def test_total_annual_budget(self):
        plan = self._plan()
        expected = 85000 * 12 + 12000 * 12 + 25000 + 20000
        assert plan.total_annual_budget() == pytest.approx(expected)

    def test_total_monthly_budget(self):
        plan = self._plan()
        # January: 85000 + 12000 + 0
        assert plan.total_monthly_budget(1) == pytest.approx(97000.0)

    def test_wrong_monthly_count_raises(self):
        bad = SAMPLE_YAML.replace(
            "[85000, 85000, 85000, 85000, 85000, 85000, 85000, 85000, 85000, 85000, 85000, 85000]",
            "[85000, 85000]",
        )
        tmp = Path("/tmp/test_budget_bad.yaml")
        tmp.write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError, match="12 monthly values"):
            BudgetPlan.from_yaml(tmp)
