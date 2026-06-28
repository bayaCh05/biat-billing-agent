"""CAPEX / asset endpoints."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.deps import get_session
from api.schemas import AssetOut, AssetCreateRequest
from src.capex.asset_repository import AssetRepository
from src.models.audit import AuditLogCreate
from src.services.audit_service import log_action, _ip, _ua

router = APIRouter(prefix="/assets", tags=["assets"])


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
def create_asset(
    body: AssetCreateRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
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

    log_action(session, AuditLogCreate(
        user_id=current_user.get("user_id"),
        user_email=current_user.get("email"),
        user_role=current_user.get("role"),
        action="CREATE",
        resource_type="Asset",
        resource_id=str(asset.id),
        after_value={
            "designation": asset.designation,
            "compte": asset.compte_immobilisation,
            "cost_ht": asset.acquisition_cost_ht,
            "useful_life_years": asset.useful_life_years,
            "method": str(asset.depreciation_method),
        },
        status="SUCCESS",
        ip_address=_ip(request),
        user_agent=_ua(request),
    ))
    session.commit()

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
