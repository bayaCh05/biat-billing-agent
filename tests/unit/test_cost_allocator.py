"""Unit tests for CostAllocator — OPEX/CAPEX allocation by JH ratio."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.billing.cost_allocator import CostAllocator
from src.models.asset import Asset
from src.models.cost_allocation import AssetProjectLink


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def allocator():
    return CostAllocator()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _asset(monthly_dep: float | None = None, **kwargs) -> Asset:
    """Build an Asset; optionally set acquisition_cost_ht so monthly_dep matches."""
    uid = uuid4()
    defaults = dict(
        id=uid,
        designation="Test Asset",
        compte_immobilisation="2183",
        compte_amortissement="2893",
        acquisition_date=date(2026, 1, 1),
        acquisition_cost_ht=36000.0,
        useful_life_years=3,
        depreciation_method="linear",
    )
    defaults.update(kwargs)
    return Asset(**defaults)


def _mock_calc(asset_id_to_amount: dict[str, float], year: int = 2026, month: int = 6):
    """Return a mock DepreciationCalculator.schedule() that maps asset_id → depreciation_amount."""
    def _schedule(asset_id, **kwargs):
        line = MagicMock()
        line.year = year
        line.month = month
        line.depreciation_amount = asset_id_to_amount.get(asset_id, 0.0)
        sched = MagicMock()
        sched.lines = [line]
        return sched

    calc = MagicMock()
    calc.schedule.side_effect = _schedule
    return calc


def _call(allocator, project_id="proj_A", all_jh=None, opex_total=40_000.0,
          asset_links=None, assets=None, calc=None, taux_jh=800.0,
          period_month=6, period_year=2026):
    return allocator.compute_allocation(
        project_id=project_id,
        period_month=period_month,
        period_year=period_year,
        all_jh=all_jh or {"proj_A": 10.0, "proj_B": 30.0},
        opex_total=opex_total,
        asset_links=asset_links or [],
        assets=assets or {},
        depreciation_calculator=calc or MagicMock(),
        taux_jh=taux_jh,
    )


# ── Basic ratio computation ───────────────────────────────────────────────────

class TestBasicRatio:
    def test_ratio_and_opex(self, allocator):
        result = _call(allocator, all_jh={"proj_A": 10.0, "proj_B": 30.0}, opex_total=40_000.0)

        assert result.allocation_ratio == pytest.approx(0.25)
        assert result.opex_allocated == pytest.approx(10_000.0)
        assert result.opex_total == 40_000.0

    def test_montant_ht(self, allocator):
        result = _call(allocator, all_jh={"proj_A": 10.0, "proj_B": 30.0}, taux_jh=800.0)

        assert result.montant_ht == pytest.approx(8_000.0)   # 10 JH × 800 TND

    def test_no_capex_when_no_links(self, allocator):
        result = _call(allocator, asset_links=[], assets={})

        assert result.capex_allocated == pytest.approx(0.0)
        assert result.capex_amort_monthly == pytest.approx(0.0)

    def test_total_cost_is_opex_plus_capex(self, allocator):
        result = _call(allocator, asset_links=[], assets={}, opex_total=40_000.0,
                       all_jh={"proj_A": 10.0, "proj_B": 30.0})

        assert result.total_cost == pytest.approx(result.opex_allocated + result.capex_allocated)

    def test_jh_fields(self, allocator):
        result = _call(allocator, all_jh={"proj_A": 10.0, "proj_B": 30.0})

        assert result.jh_allocated == 10.0
        assert result.jh_total == 40.0
        assert result.jh_billed == 10.0


# ── Zero / edge cases ─────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_zero_total_jh_no_division_error(self, allocator):
        result = _call(allocator, all_jh={"proj_A": 0.0})

        assert result.allocation_ratio == pytest.approx(0.0)
        assert result.opex_allocated == pytest.approx(0.0)
        assert result.montant_ht == pytest.approx(0.0)

    def test_project_not_in_jh_dict(self, allocator):
        result = _call(allocator, project_id="proj_A",
                       all_jh={"proj_B": 10.0, "proj_C": 20.0})

        assert result.jh_allocated == 0.0
        assert result.allocation_ratio == pytest.approx(0.0)
        assert result.montant_ht == pytest.approx(0.0)
        assert result.opex_allocated == pytest.approx(0.0)

    def test_single_project_gets_full_budget(self, allocator):
        result = _call(allocator, all_jh={"proj_A": 15.0}, opex_total=30_000.0)

        assert result.allocation_ratio == pytest.approx(1.0)
        assert result.opex_allocated == pytest.approx(30_000.0)

    def test_output_fields_populated(self, allocator):
        result = _call(allocator, project_id="proj_A",
                       all_jh={"proj_A": 10.0, "proj_B": 30.0})

        assert result.project_id == "proj_A"
        assert result.period_month == 6
        assert result.period_year == 2026


# ── CAPEX allocation ──────────────────────────────────────────────────────────

class TestCapexAllocation:
    def test_single_asset_single_link(self, allocator):
        asset = _asset()
        link = AssetProjectLink(
            asset_id=str(asset.id),
            project_id="proj_A",
            allocation_pct=60.0,
        )
        calc = _mock_calc({str(asset.id): 1_000.0})

        result = _call(
            allocator,
            all_jh={"proj_A": 10.0},
            opex_total=0.0,
            asset_links=[link],
            assets={str(asset.id): asset},
            calc=calc,
        )

        assert result.capex_allocated == pytest.approx(600.0)   # 1000 × 0.60

    def test_capex_adds_to_total_cost(self, allocator):
        asset = _asset()
        link = AssetProjectLink(
            asset_id=str(asset.id), project_id="proj_A", allocation_pct=50.0
        )
        calc = _mock_calc({str(asset.id): 1_000.0})

        result = _call(
            allocator,
            all_jh={"proj_A": 10.0, "proj_B": 30.0},
            opex_total=40_000.0,
            asset_links=[link],
            assets={str(asset.id): asset},
            calc=calc,
        )

        expected_capex = 1_000.0 * 0.50
        expected_opex  = 40_000.0 * 0.25
        assert result.capex_allocated == pytest.approx(expected_capex)
        assert result.total_cost == pytest.approx(expected_opex + expected_capex)

    def test_link_for_different_project_ignored(self, allocator):
        asset = _asset()
        link_other = AssetProjectLink(
            asset_id=str(asset.id), project_id="proj_B", allocation_pct=100.0
        )
        calc = _mock_calc({str(asset.id): 1_000.0})

        result = _call(
            allocator,
            project_id="proj_A",
            all_jh={"proj_A": 10.0},
            asset_links=[link_other],
            assets={str(asset.id): asset},
            calc=calc,
        )

        assert result.capex_allocated == pytest.approx(0.0)

    def test_asset_missing_from_dict_skipped_silently(self, allocator):
        link = AssetProjectLink(
            asset_id="asset-ghost", project_id="proj_A", allocation_pct=100.0
        )
        calc = MagicMock()

        result = _call(
            allocator,
            project_id="proj_A",
            all_jh={"proj_A": 10.0},
            asset_links=[link],
            assets={},             # ghost asset not present
            calc=calc,
        )

        assert result.capex_allocated == pytest.approx(0.0)
        calc.schedule.assert_not_called()   # never reached the depreciation call

    def test_multiple_assets_summed(self, allocator):
        a1, a2 = _asset(), _asset()
        link1 = AssetProjectLink(asset_id=str(a1.id), project_id="proj_A", allocation_pct=40.0)
        link2 = AssetProjectLink(asset_id=str(a2.id), project_id="proj_A", allocation_pct=30.0)
        calc = _mock_calc({str(a1.id): 1_000.0, str(a2.id): 500.0})

        result = _call(
            allocator,
            all_jh={"proj_A": 10.0},
            opex_total=0.0,
            asset_links=[link1, link2],
            assets={str(a1.id): a1, str(a2.id): a2},
            calc=calc,
        )

        # 1000 × 0.40 + 500 × 0.30 = 400 + 150 = 550
        assert result.capex_allocated == pytest.approx(550.0)

    def test_asset_outside_depreciation_period_returns_zero(self, allocator):
        """An asset not yet acquired in the period gives 0 monthly depreciation."""
        asset = _asset()
        link = AssetProjectLink(
            asset_id=str(asset.id), project_id="proj_A", allocation_pct=100.0
        )
        # Mock calc returns a schedule with no lines matching year=2026, month=6
        no_match_line = MagicMock()
        no_match_line.year = 2025
        no_match_line.month = 12
        no_match_line.depreciation_amount = 1_000.0
        sched = MagicMock()
        sched.lines = [no_match_line]
        calc = MagicMock()
        calc.schedule.return_value = sched

        result = _call(
            allocator,
            all_jh={"proj_A": 10.0},
            asset_links=[link],
            assets={str(asset.id): asset},
            calc=calc,
        )

        assert result.capex_allocated == pytest.approx(0.0)
