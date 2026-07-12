"""CAPEX / asset endpoints."""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, status

from api.auth import require_role
from api.schemas import AssetOut, AssetCreateRequest

router = APIRouter(prefix="/assets", tags=["assets"])

_log = logging.getLogger(__name__)

_COMPTABLE_DIRECTION = Depends(require_role("Comptable", "Direction"))


@router.get(
    "",
    response_model=list[AssetOut],
    summary="Lister les immobilisations",
    description=(
        "Retourne le registre CAPEX de toutes les immobilisations. "
        "Le paramètre `include_fully_depreciated=false` exclut les actifs totalement amortis. "
        "La valeur nette comptable est calculée dynamiquement à la date du jour."
    ),
    response_description="Liste des immobilisations avec méthode et état d'amortissement",
)
async def list_assets(
    include_fully_depreciated: bool = True,
):
    from src.storage.documents.service_bridge import list_assets_mongo

    mongo_assets = await list_assets_mongo(include_fully_depreciated)
    if mongo_assets is None:
        # Assets are written Mongo-only (see CLAUDE.md) — the old SQLite
        # fallback here could only ever serve permanently stale data.
        _log.warning("list_assets: MongoDB indisponible — retour d'une liste vide.")
        assets = []
    else:
        assets = mongo_assets
    today = date.today()
    return [
        AssetOut(
            id=str(a.id),
            designation=a.designation,
            compte_immobilisation=a.compte_immobilisation,
            compte_amortissement=a.compte_amortissement,
            acquisition_date=a.acquisition_date,
            acquisition_cost_ht=a.acquisition_cost_ht,
            useful_life_years=a.useful_life_years,
            depreciation_method=str(a.depreciation_method),
            fully_depreciated=a.book_value_at(today) <= 0,
        )
        for a in assets
    ]


@router.post(
    "",
    response_model=AssetOut,
    status_code=status.HTTP_201_CREATED,
    summary="Enregistrer une immobilisation",
    description=(
        "Crée une nouvelle immobilisation dans le registre CAPEX. "
        "Méthodes d'amortissement supportées : `linear` (linéaire) ou `degressive` (dégressif). "
        "Le plan d'amortissement PCE (compte 6811 / 28xx) est calculé automatiquement sur la durée de vie."
    ),
    response_description="Immobilisation créée avec son état d'amortissement au jour J",
)
async def create_asset(
    body: AssetCreateRequest,
    current_user: dict = _COMPTABLE_DIRECTION,
):
    from src.storage.documents.service_bridge import create_asset_native

    asset = await create_asset_native(body, current_user)

    today = date.today()
    return AssetOut(
        id=str(asset.id),
        designation=asset.designation,
        compte_immobilisation=asset.compte_immobilisation,
        compte_amortissement=asset.compte_amortissement,
        acquisition_date=asset.acquisition_date,
        acquisition_cost_ht=asset.acquisition_cost_ht,
        useful_life_years=asset.useful_life_years,
        depreciation_method=str(asset.depreciation_method),
        fully_depreciated=asset.book_value_at(today) <= 0,
    )
