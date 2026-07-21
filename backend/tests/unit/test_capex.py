"""Unit tests for src/capex — DepreciationCalculator, AssetRepository, DepreciationEntryGenerator."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.capex.depreciation_calculator import (
    DepreciationCalculator,
    _next_month,
)
from src.capex.depreciation_entry_generator import DepreciationEntryGenerator, _last_day_of_month
from src.capex.asset_repository import AssetRepository, AssetORM
from src.models.asset import Asset
from src.accounting.plan_comptable import ComptesAmortissement


# ── Helpers ───────────────────────────────────────────────────────────────────

def _asset(**kwargs) -> Asset:
    defaults = dict(
        id=uuid4(),
        designation="Serveur Dell",
        compte_immobilisation="2183",
        compte_amortissement="2893",
        acquisition_date=date(2024, 1, 1),
        acquisition_cost_ht=12000.0,
        useful_life_years=3,
        depreciation_method="linear",
    )
    defaults.update(kwargs)
    return Asset(**defaults)


# ── _next_month ───────────────────────────────────────────────────────────────

class TestNextMonth:
    def test_regular(self):
        assert _next_month(2024, 6) == (2024, 7)

    def test_december_wraps(self):
        assert _next_month(2024, 12) == (2025, 1)

    def test_january(self):
        assert _next_month(2025, 1) == (2025, 2)


# ── DepreciationCalculator — linear ──────────────────────────────────────────

class TestLinearDepreciation:
    def setup_method(self):
        self.calc = DepreciationCalculator()

    def _schedule(self, cost=12000.0, years=3, start=date(2024, 1, 1)):
        return self.calc.schedule(
            asset_id="test", designation="Test", acquisition_cost_ht=cost,
            acquisition_date=start, useful_life_years=years, method="linear",
        )

    def test_total_months(self):
        sched = self._schedule(years=3)
        assert len(sched.lines) == 36

    def test_total_depreciation_equals_cost(self):
        sched = self._schedule(cost=12000.0, years=3)
        assert sched.total_depreciated == pytest.approx(12000.0, abs=0.01)

    def test_final_book_value_is_zero(self):
        sched = self._schedule()
        assert sched.final_book_value == pytest.approx(0.0, abs=0.01)

    def test_book_value_decreases_monotonically(self):
        sched = self._schedule()
        vncs = [ln.book_value for ln in sched.lines]
        assert all(vncs[i] >= vncs[i + 1] for i in range(len(vncs) - 1))

    def test_monthly_amount_constant(self):
        sched = self._schedule(cost=12000.0, years=1)
        amounts = [ln.depreciation_amount for ln in sched.lines[:-1]]
        assert all(abs(a - amounts[0]) < 0.01 for a in amounts)

    def test_method_used_is_linear(self):
        sched = self._schedule()
        assert all(ln.method_used == "linear" for ln in sched.lines)

    def test_cumulated_depreciation_last_equals_cost(self):
        sched = self._schedule(cost=5000.0, years=5)
        assert sched.lines[-1].cumulated_depreciation == pytest.approx(5000.0, abs=0.01)

    def test_period_labels(self):
        sched = self._schedule(years=1, start=date(2024, 11, 1))
        assert sched.lines[0].period_label == "2024-11"
        assert sched.lines[1].period_label == "2024-12"
        assert sched.lines[2].period_label == "2025-01"

    def test_lines_for_year(self):
        sched = self._schedule(years=3, start=date(2024, 1, 1))
        assert len(sched.lines_for_year(2024)) == 12
        assert len(sched.lines_for_year(2025)) == 12
        assert len(sched.lines_for_year(2026)) == 12

    def test_annual_depreciation_for_year(self):
        sched = self._schedule(cost=12000.0, years=1, start=date(2024, 1, 1))
        annual = sched.annual_depreciation_for_year(2024)
        assert annual == pytest.approx(12000.0, abs=0.01)

    def test_five_year_asset(self):
        sched = self._schedule(cost=50000.0, years=5)
        assert len(sched.lines) == 60
        assert sched.total_depreciated == pytest.approx(50000.0, abs=0.01)

    def test_book_value_at_midpoint(self):
        sched = self._schedule(cost=12000.0, years=1, start=date(2024, 1, 1))
        # After 6 months, VNC should be ~50%
        mid_line = sched.lines[5]  # June
        assert mid_line.book_value == pytest.approx(6000.0, abs=10.0)


# ── DepreciationCalculator — degressive ──────────────────────────────────────

class TestDegressiveDepreciation:
    def setup_method(self):
        self.calc = DepreciationCalculator()

    def _schedule(self, cost=12000.0, years=3, start=date(2024, 1, 1)):
        return self.calc.schedule(
            asset_id="test", designation="Test", acquisition_cost_ht=cost,
            acquisition_date=start, useful_life_years=years, method="degressive",
        )

    def test_total_months(self):
        sched = self._schedule(years=3)
        assert len(sched.lines) == 36

    def test_total_depreciation_equals_cost(self):
        sched = self._schedule(cost=12000.0, years=3)
        assert sched.total_depreciated == pytest.approx(12000.0, abs=0.01)

    def test_final_book_value_is_zero(self):
        sched = self._schedule()
        assert sched.final_book_value == pytest.approx(0.0, abs=0.01)

    def test_early_months_depreciate_faster_than_late(self):
        sched = self._schedule(cost=12000.0, years=4)
        first_half = sum(ln.depreciation_amount for ln in sched.lines[:24])
        second_half = sum(ln.depreciation_amount for ln in sched.lines[24:])
        assert first_half > second_half

    def test_coefficient_4_years(self):
        assert self.calc._degressive_coefficient(4) == 1.5

    def test_coefficient_6_years(self):
        assert self.calc._degressive_coefficient(6) == 2.0

    def test_coefficient_10_years(self):
        assert self.calc._degressive_coefficient(10) == 2.5

    def test_unknown_method_raises(self):
        with pytest.raises(ValueError, match="Unknown depreciation method"):
            self.calc.schedule(
                asset_id="x", designation="x", acquisition_cost_ht=1000.0,
                acquisition_date=date(2024, 1, 1), useful_life_years=3,
                method="unknown_method",
            )

    def test_book_value_at_helper(self):
        vnc = self.calc.book_value_at(
            acquisition_cost_ht=12000.0,
            acquisition_date=date(2024, 1, 1),
            useful_life_years=1,
            ref_date=date(2024, 12, 31),
            method="linear",
        )
        assert vnc == pytest.approx(0.0, abs=0.1)

    def test_book_value_at_before_acquisition(self):
        vnc = self.calc.book_value_at(
            acquisition_cost_ht=12000.0,
            acquisition_date=date(2025, 1, 1),
            useful_life_years=3,
            ref_date=date(2024, 6, 1),
            method="linear",
        )
        assert vnc == pytest.approx(12000.0, abs=0.01)


# ── DepreciationEntryGenerator ────────────────────────────────────────────────

class TestDepreciationEntryGenerator:
    def setup_method(self):
        self.gen = DepreciationEntryGenerator()
        self.asset = _asset()

    def test_monthly_entry_reference(self):
        entry = self.gen.monthly_entry(self.asset, 2024, 3, 333.333)
        assert "2024-03" in entry.reference

    def test_monthly_entry_balance(self):
        entry = self.gen.monthly_entry(self.asset, 2024, 1, 1000.0)
        total_debit = sum(ln.debit or 0 for ln in entry.lines)
        total_credit = sum(ln.credit or 0 for ln in entry.lines)
        assert abs(total_debit - total_credit) < 0.005

    def test_monthly_entry_compte_6811(self):
        entry = self.gen.monthly_entry(self.asset, 2024, 1, 500.0)
        debit_comptes = [ln.compte for ln in entry.lines if ln.debit]
        assert "6811" in debit_comptes

    def test_monthly_entry_compte_amort(self):
        entry = self.gen.monthly_entry(self.asset, 2024, 1, 500.0)
        credit_comptes = [ln.compte for ln in entry.lines if ln.credit]
        expected = ComptesAmortissement.get_amort_compte(self.asset.compte_immobilisation)
        assert expected in credit_comptes

    def test_monthly_entry_date_end_of_month(self):
        entry = self.gen.monthly_entry(self.asset, 2024, 2, 100.0)
        assert entry.date_ecriture == date(2024, 2, 29)  # 2024 is leap year

    def test_monthly_entry_date_end_of_month_non_leap(self):
        entry = self.gen.monthly_entry(self.asset, 2025, 2, 100.0)
        assert entry.date_ecriture == date(2025, 2, 28)

    def test_annual_entry_balance(self):
        entry = self.gen.annual_entry(self.asset, 2024, 12000.0)
        total_debit = sum(ln.debit or 0 for ln in entry.lines)
        total_credit = sum(ln.credit or 0 for ln in entry.lines)
        assert abs(total_debit - total_credit) < 0.005

    def test_annual_entry_date(self):
        entry = self.gen.annual_entry(self.asset, 2024, 4000.0)
        assert entry.date_ecriture == date(2024, 12, 31)

    def test_annual_entry_source_asset_id(self):
        entry = self.gen.annual_entry(self.asset, 2024, 4000.0)
        assert entry.source_asset_id == self.asset.id

    def test_monthly_entry_amount_rounded(self):
        entry = self.gen.monthly_entry(self.asset, 2024, 1, 333.33333)
        debit_line = next(ln for ln in entry.lines if ln.debit)
        assert str(debit_line.debit).count(".") <= 1
        assert debit_line.debit == pytest.approx(333.333, abs=0.001)


# ── _last_day_of_month ────────────────────────────────────────────────────────

class TestLastDayOfMonth:
    def test_january(self):
        assert _last_day_of_month(2024, 1) == 31

    def test_february_leap(self):
        assert _last_day_of_month(2024, 2) == 29

    def test_february_non_leap(self):
        assert _last_day_of_month(2025, 2) == 28

    def test_april(self):
        assert _last_day_of_month(2024, 4) == 30

    def test_december(self):
        assert _last_day_of_month(2024, 12) == 31


# ── AssetRepository (mock session) ───────────────────────────────────────────

class TestAssetRepository:
    def _repo(self):
        session = MagicMock()
        session.get.return_value = None
        session.execute.return_value.scalars.return_value.all.return_value = []
        session.execute.return_value.scalar_one.return_value = 0
        return AssetRepository(session), session

    def test_save_new_asset_calls_add(self):
        repo, session = self._repo()
        asset = _asset()
        repo.save(asset)
        session.add.assert_called_once()
        session.commit.assert_called_once()

    def test_save_existing_asset_updates(self):
        repo, session = self._repo()
        asset = _asset()
        existing_orm = MagicMock(spec=AssetORM)
        session.get.return_value = existing_orm
        repo.save(asset)
        session.add.assert_not_called()
        session.commit.assert_called_once()

    def test_get_by_id_returns_none_when_not_found(self):
        repo, session = self._repo()
        session.get.return_value = None
        result = repo.get_by_id(uuid4())
        assert result is None

    def test_list_all_returns_empty_list(self):
        repo, session = self._repo()
        result = repo.list_all()
        assert result == []

    def test_count_returns_zero(self):
        repo, session = self._repo()
        assert repo.count() == 0

    def test_total_gross_value_returns_zero(self):
        repo, session = self._repo()
        assert repo.total_gross_value() == 0.0

    def test_mark_fully_depreciated(self):
        repo, session = self._repo()
        orm = MagicMock(spec=AssetORM)
        session.get.return_value = orm
        repo.mark_fully_depreciated(uuid4())
        assert orm.fully_depreciated is True
        session.commit.assert_called_once()

    def test_delete_returns_false_when_not_found(self):
        repo, session = self._repo()
        session.get.return_value = None
        assert repo.delete(uuid4()) is False

    def test_delete_returns_true_when_found(self):
        repo, session = self._repo()
        session.get.return_value = MagicMock(spec=AssetORM)
        assert repo.delete(uuid4()) is True
        session.commit.assert_called_once()


# ── Asset model (book_value_at) ───────────────────────────────────────────────

class TestAssetModel:
    def test_annual_depreciation(self):
        a = _asset(acquisition_cost_ht=12000.0, useful_life_years=3)
        assert a.annual_depreciation == pytest.approx(4000.0)

    def test_monthly_depreciation(self):
        a = _asset(acquisition_cost_ht=12000.0, useful_life_years=1)
        assert a.monthly_depreciation == pytest.approx(1000.0)

    def test_book_value_at_acquisition(self):
        a = _asset(acquisition_cost_ht=12000.0, useful_life_years=3, acquisition_date=date(2024, 1, 1))
        vnc = a.book_value_at(date(2024, 1, 1))
        assert vnc == pytest.approx(12000.0, abs=50)

    def test_book_value_at_end(self):
        a = _asset(acquisition_cost_ht=12000.0, useful_life_years=3, acquisition_date=date(2024, 1, 1))
        vnc = a.book_value_at(date(2027, 1, 1))
        # monthly rounding (333.333 × 36 = 11999.988) leaves a small residual — abs=0.02
        assert vnc == pytest.approx(0.0, abs=0.02)

    def test_book_value_non_negative(self):
        a = _asset(acquisition_cost_ht=12000.0, useful_life_years=1, acquisition_date=date(2020, 1, 1))
        assert a.book_value_at(date(2030, 1, 1)) == 0.0
