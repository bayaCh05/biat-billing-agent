"""OPEX/CAPEX cost allocation across projects by JH ratio."""
from __future__ import annotations

from src.capex.depreciation_calculator import DepreciationCalculator
from src.models.asset import Asset
from src.models.cost_allocation import AssetProjectLink, ProjectCostAllocation


class CostAllocator:
    """Allocates OPEX and CAPEX costs to a project for a given period.

    Cost sharing logic:
      - Each project's share = its JH / total JH across all projects.
      - OPEX (salaries, telecom, maintenance, …) is split by that ratio.
      - CAPEX is expressed as monthly depreciation VALUE per asset, then
        weighted by the asset's allocation percentage for this project.
        Example: server 12 000 TND / 36 months = 333.33 TND/month;
        if 60% is allocated to project A → 200 TND/month for project A.
    """

    def compute_allocation(
        self,
        project_id: str,
        period_month: int,
        period_year: int,
        all_jh: dict[str, float],          # project_id → JH consumed this period
        opex_total: float,                  # total OPEX charges for the period
        asset_links: list[AssetProjectLink],
        assets: dict[str, Asset],           # asset_id (str) → Asset
        depreciation_calculator: DepreciationCalculator,
        taux_jh: float,                     # fixed daily rate in TND
    ) -> ProjectCostAllocation:
        total_jh = sum(all_jh.values())
        jh_proj  = all_jh.get(project_id, 0.0)
        ratio    = (jh_proj / total_jh) if total_jh > 0 else 0.0

        opex_allocated = round(opex_total * ratio, 3)

        # CAPEX: sum monthly depreciation value for assets linked to this project
        capex_monthly = 0.0
        for link in asset_links:
            if link.project_id != project_id:
                continue
            asset = assets.get(link.asset_id)
            if asset is None:
                continue
            monthly_dep = self._monthly_depreciation(
                asset, period_year, period_month, depreciation_calculator
            )
            capex_monthly += round(monthly_dep * (link.allocation_pct / 100), 3)
        capex_monthly = round(capex_monthly, 3)

        return ProjectCostAllocation(
            project_id=project_id,
            period_month=period_month,
            period_year=period_year,
            jh_allocated=jh_proj,
            jh_total=total_jh,
            allocation_ratio=round(ratio, 6),
            opex_total=opex_total,
            opex_allocated=opex_allocated,
            capex_amort_monthly=capex_monthly,
            capex_allocated=capex_monthly,
            total_cost=round(opex_allocated + capex_monthly, 3),
            jh_billed=jh_proj,
            taux_jh=taux_jh,
            montant_ht=round(jh_proj * taux_jh, 3),
        )

    @staticmethod
    def _monthly_depreciation(
        asset: Asset,
        year: int,
        month: int,
        calc: DepreciationCalculator,
    ) -> float:
        """Return the depreciation amount for a specific month by walking the schedule."""
        sched = calc.schedule(
            asset_id=str(asset.id),
            designation=asset.designation,
            acquisition_cost_ht=asset.acquisition_cost_ht,
            acquisition_date=asset.acquisition_date,
            useful_life_years=asset.useful_life_years,
            method=asset.depreciation_method,
        )
        for line in sched.lines:
            if line.year == year and line.month == month:
                return line.depreciation_amount
        return 0.0  # asset not yet started or fully depreciated in this period
