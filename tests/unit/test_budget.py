"""Unit tests for src/budget — BudgetTracker and CostAnalyzer."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch
import io

import pytest
import yaml

from src.budget.budget_tracker import (
    BudgetLine,
    BudgetPlan,
    BudgetTracker,
    MonthlyVariance,
    YearVariance,
    _last_day,
)
from src.budget.cost_analyzer import CostAnalyzer, _subtract_months


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


# ── BudgetTracker ─────────────────────────────────────────────────────────────

class TestBudgetTracker:
    def _plan(self):
        tmp = Path("/tmp/test_bt_plan.yaml")
        tmp.write_text(SAMPLE_YAML, encoding="utf-8")
        return BudgetPlan.from_yaml(tmp)

    def _tracker(self, actuals: dict[str, float]):
        """actuals: {catalog_id: amount_ht}"""
        session = MagicMock()
        mock_rows = [
            MagicMock(cost_catalog_id=k, total=v)
            for k, v in actuals.items()
        ]
        session.execute.return_value.all.return_value = mock_rows
        return BudgetTracker(plan=self._plan(), session=session)

    def test_monthly_variance_returns_all_lines(self):
        tracker = self._tracker({})
        mv_list = tracker.monthly_variance(2026, 1)
        assert len(mv_list) == 3

    def test_monthly_variance_zero_actual(self):
        tracker = self._tracker({})
        mv_list = tracker.monthly_variance(2026, 1)
        salaires_mv = next(mv for mv in mv_list if mv.catalog_id == "salaires")
        assert salaires_mv.actual == 0.0
        assert salaires_mv.budget == 85000.0

    def test_monthly_variance_with_actual(self):
        tracker = self._tracker({"salaires": 90000.0})
        mv_list = tracker.monthly_variance(2026, 1)
        salaires_mv = next(mv for mv in mv_list if mv.catalog_id == "salaires")
        assert salaires_mv.actual == pytest.approx(90000.0)
        assert salaires_mv.variance == pytest.approx(5000.0)

    def test_ytd_variance_aggregates_monthly(self):
        # Single query now returns one row per (catalog_id, month)
        session = MagicMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [
            MagicMock(cost_catalog_id="salaires", month="01", total=80000.0),
            MagicMock(cost_catalog_id="salaires", month="02", total=80000.0),
            MagicMock(cost_catalog_id="salaires", month="03", total=80000.0),
        ]
        session.execute.return_value = mock_result
        plan = self._plan()
        tracker = BudgetTracker(plan=plan, session=session)
        ytd = tracker.ytd_variance(2026, 3)

        salaires_yv = next(yv for yv in ytd if yv.catalog_id == "salaires")
        assert salaires_yv.actual_ytd == pytest.approx(80000.0 * 3)
        assert salaires_yv.budget_ytd == pytest.approx(85000.0 * 3)
        assert salaires_yv.variance_ytd == pytest.approx(-15000.0)

    def test_summary_keys(self):
        tracker = self._tracker({})
        s = tracker.summary(2026, 6)
        assert "total_budget_ytd" in s
        assert "total_actual_ytd" in s
        assert "total_variance_ytd" in s
        assert "lines_over_budget" in s
        assert "top_overruns" in s


# ── Helpers ───────────────────────────────────────────────────────────────────

class TestHelpers:
    def test_last_day_regular(self):
        assert _last_day(2026, 3) == date(2026, 3, 31)

    def test_last_day_december(self):
        assert _last_day(2026, 12) == date(2026, 12, 31)

    def test_last_day_february_leap(self):
        assert _last_day(2024, 2) == date(2024, 2, 29)

    def test_last_day_february_non_leap(self):
        assert _last_day(2026, 2) == date(2026, 2, 28)

    def test_subtract_months_simple(self):
        y, m = _subtract_months(2026, 6, 3)
        assert (y, m) == (2026, 3)

    def test_subtract_months_crosses_year(self):
        y, m = _subtract_months(2026, 2, 4)
        assert (y, m) == (2025, 10)

    def test_subtract_months_to_december(self):
        y, m = _subtract_months(2026, 1, 1)
        assert (y, m) == (2025, 12)


# ── CostAnalyzer ─────────────────────────────────────────────────────────────

class TestCostAnalyzer:
    def _analyzer(self, trend_rows=None, anomaly_current=None, anomaly_history=None):
        session = MagicMock()

        call_n = [0]

        def side_effect(stmt):
            mock = MagicMock()
            call_n[0] += 1
            if anomaly_current is not None and call_n[0] == 1:
                mock.all.return_value = anomaly_current
            elif anomaly_history is not None:
                mock.all.return_value = anomaly_history
            else:
                mock.all.return_value = trend_rows or []
            return mock

        session.execute.side_effect = side_effect
        return CostAnalyzer(session=session, min_history_months=2)

    def test_trends_returns_trend_points(self):
        row = MagicMock(yr=2026.0, mo=1.0, cost_catalog_id="salaires", total=85000.0, cnt=1)
        analyzer = self._analyzer(trend_rows=[row])
        points = analyzer.trends()
        assert len(points) == 1
        assert points[0].catalog_id == "salaires"
        assert points[0].amount == pytest.approx(85000.0)
        assert points[0].period_label == "2026-01"

    def test_trends_empty(self):
        analyzer = self._analyzer(trend_rows=[])
        assert analyzer.trends() == []

    def test_anomalies_no_history(self):
        current_row = MagicMock(cost_catalog_id="salaires", total=200000.0, cnt=1)
        # history < min_history_months → no anomalies
        history_row = MagicMock(yr=2026.0, mo=1.0, total=85000.0)

        session = MagicMock()
        calls = [0]

        def se(stmt):
            mock = MagicMock()
            calls[0] += 1
            if calls[0] == 1:
                mock.all.return_value = [current_row]
            else:
                mock.all.return_value = [history_row]   # only 1 month → below min_history_months=2
            return mock

        session.execute.side_effect = se
        analyzer = CostAnalyzer(session=session, min_history_months=2)
        result = analyzer.anomalies(2026, 3)
        assert result == []

    def test_anomalies_critical(self):
        current_row = MagicMock(cost_catalog_id="salaires", total=200000.0, cnt=2)
        history_rows = [
            MagicMock(yr=2026.0, mo=1.0, total=90000.0),
            MagicMock(yr=2026.0, mo=2.0, total=90000.0),
            MagicMock(yr=2026.0, mo=3.0, total=90000.0),
        ]

        session = MagicMock()
        calls = [0]

        def se(stmt):
            mock = MagicMock()
            calls[0] += 1
            if calls[0] == 1:
                mock.all.return_value = [current_row]
            else:
                mock.all.return_value = history_rows
            return mock

        session.execute.side_effect = se
        analyzer = CostAnalyzer(session=session, min_history_months=2, critical_ratio=2.0)
        result = analyzer.anomalies(2026, 4)
        assert len(result) == 1
        assert result[0].severity == "critical"
        assert result[0].ratio == pytest.approx(200000 / 90000, abs=0.01)

    def test_top_categories_returns_sorted(self):
        rows = [
            MagicMock(cost_catalog_id="salaires",     total=500000.0, cnt=10),
            MagicMock(cost_catalog_id="loyers",       total=144000.0, cnt=12),
            MagicMock(cost_catalog_id="licences_saas",total=180000.0, cnt=12),
        ]
        session = MagicMock()
        session.execute.return_value.all.return_value = rows
        analyzer = CostAnalyzer(session=session)
        top = analyzer.top_categories(2026, 6)
        assert len(top) == 3
        assert top[0]["catalog_id"] == "salaires"
        assert top[0]["pct_of_total"] == pytest.approx(60.6, abs=0.2)
