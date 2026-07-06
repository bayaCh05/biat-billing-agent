"""Pydantic models for OPEX/CAPEX cost allocation across projects by JH ratio."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class CostNature(str, Enum):
    OPEX  = "opex"
    CAPEX = "capex"


class ProjectCostAllocation(BaseModel):
    project_id: str
    period_month: int
    period_year: int

    # JH allocation
    jh_allocated: float            # JH assigned to this project this period
    jh_total: float                # total JH across all projects this period
    allocation_ratio: float        # jh_allocated / jh_total

    # OPEX share
    opex_total: float              # total OPEX charges for the period
    opex_allocated: float          # opex_total * allocation_ratio

    # CAPEX share (amortissement expressed as monthly monetary value per asset)
    capex_amort_monthly: float     # sum of monthly depreciation of assets linked
                                   # to this project (e.g. 12 000 TND / 36 months
                                   # = 333.33 TND/month per server)
    capex_allocated: float         # capex_amort_monthly * allocation_ratio

    # Total cost allocated to this project for this period
    total_cost: float              # opex_allocated + capex_allocated

    # Billing amounts
    jh_billed: float               # JH appearing on the invoice line
    taux_jh: float                 # daily rate in TND
    montant_ht: float              # jh_billed * taux_jh


class AssetProjectLink(BaseModel):
    asset_id: str
    project_id: str
    allocation_pct: float          # 0–100; sum across all projects for an asset = 100
