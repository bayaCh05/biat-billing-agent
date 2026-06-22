"""CAPEX / asset endpoints."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import get_session
from api.schemas import AssetOut
from src.capex.asset_repository import AssetRepository

router = APIRouter(prefix="/assets", tags=["capex"])


@router.get("", response_model=list[AssetOut])
def list_assets(
    include_fully_depreciated: bool = True,
    session: Session = Depends(get_session),
):
    repo = AssetRepository(session)
    assets = repo.list_all(include_fully_depreciated=include_fully_depreciated)
    today = date.today()
    return [
        AssetOut(
            id=str(a.id),
            designation=a.designation,
            compte_immobilisation=a.compte_immobilisation,
            acquisition_date=a.acquisition_date,
            acquisition_cost_ht=a.acquisition_cost_ht,
            useful_life_years=a.useful_life_years,
            depreciation_method=str(a.depreciation_method),
            fully_depreciated=a.book_value_at(today) <= 0,
        )
        for a in assets
    ]
