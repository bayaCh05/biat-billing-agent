"""CAPEX / asset endpoints."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from api.deps import get_session
from api.schemas import AssetOut, AssetCreateRequest
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


@router.post("", response_model=AssetOut, status_code=status.HTTP_201_CREATED)
def create_asset(body: AssetCreateRequest, session: Session = Depends(get_session)):
    from src.models.asset import Asset

    asset = Asset(
        designation=body.designation,
        compte_immobilisation=body.compte_immobilisation,
        compte_amortissement=body.compte_amortissement,
        acquisition_date=body.acquisition_date,
        acquisition_cost_ht=body.acquisition_cost_ht,
        useful_life_years=body.useful_life_years,
        depreciation_method=body.depreciation_method,
    )
    repo = AssetRepository(session)
    repo.save(asset)
    today = date.today()
    return AssetOut(
        id=str(asset.id),
        designation=asset.designation,
        compte_immobilisation=asset.compte_immobilisation,
        acquisition_date=asset.acquisition_date,
        acquisition_cost_ht=asset.acquisition_cost_ht,
        useful_life_years=asset.useful_life_years,
        depreciation_method=str(asset.depreciation_method),
        fully_depreciated=asset.book_value_at(today) <= 0,
    )
