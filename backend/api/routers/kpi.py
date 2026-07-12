"""KPI and analytics endpoints for Direction / Comptable dashboards."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.auth import require_role
from api.schemas import KpiOut

router = APIRouter(prefix="/kpi", tags=["analytics"])
analytics_router = APIRouter(prefix="/analytics", tags=["analytics"])

_log = logging.getLogger(__name__)

_DIRECTION_COMPTABLE = Depends(require_role("Admin", "Direction", "Comptable"))


# ── Main KPI endpoint — pure SQL aggregation, no full table scan ──────────────

@router.get(
    "",
    response_model=KpiOut,
    summary="KPIs du tableau de bord",
    description=(
        "Métriques globales du système : nombre total de factures, montant traité TTC, "
        "taux d'approbation automatique (sans intervention humaine), "
        "factures en attente de révision et répartition par statut."
    ),
    response_description="Compteurs et taux agrégés sur l'ensemble des factures",
)
async def get_kpi():
    from src.storage.documents.service_bridge import get_kpi_mongo

    mongo_result = await get_kpi_mongo()
    if mongo_result is None:
        # Invoices are written Mongo-only (see CLAUDE.md) — the old SQLite
        # fallback here could only ever serve permanently stale data.
        _log.warning("get_kpi: MongoDB indisponible — retour de KPIs vides.")
        return KpiOut(
            total_invoices=0, total_amount_ttc=0.0, auto_approved=0,
            auto_approval_rate=0.0, flagged=0, pending_review=0, by_status={},
        )
    return KpiOut(**mongo_result)


# ── Analytics schemas ──────────────────────────────────────────────────────────

class MonthlySpendItem(BaseModel):
    month: str          # "2026-01"
    total_ht: float
    total_ttc: float
    invoice_count: int
    opex: float
    capex: float


class SupplierSpendItem(BaseModel):
    supplier: str
    total_ttc: float
    total_ht: float
    count: int


class AccountSpendItem(BaseModel):
    compte: str
    label: str
    total_ht: float
    pct: float


class AnalyticsKPIs(BaseModel):
    avg_processing_days: float
    rejection_rate: float
    human_review_rate: float
    total_capex_ytd: float
    total_opex_ytd: float
    pending_count: int


# ── 1. Monthly spend with OPEX/CAPEX split ─────────────────────────────────────

@analytics_router.get(
    "/monthly-spend",
    response_model=list[MonthlySpendItem],
    summary="Dépenses mensuelles OPEX / CAPEX fournisseurs",
    description=(
        "Agrège les factures fournisseurs traitées par mois (SQL GROUP BY). "
        "Retourne 12 points pour l'année demandée, avec ventilation OPEX / CAPEX "
        "basée sur la nature comptable (charge_type)."
    ),
)
async def monthly_spend(
    year: int = Query(2026, description="Année fiscale"),
    _: dict = _DIRECTION_COMPTABLE,
):
    from src.storage.documents.service_bridge import monthly_spend_mongo

    months = [f"{year}-{m:02d}" for m in range(1, 13)]
    mongo_result = await monthly_spend_mongo(year)
    if mongo_result is None:
        # Invoices are written Mongo-only (see CLAUDE.md) — the old SQLite
        # fallback here could only ever serve permanently stale data.
        _log.warning("monthly_spend: MongoDB indisponible — retour de valeurs vides.")
        by_month: dict[str, MonthlySpendItem] = {}
    else:
        by_month = {r["month"]: MonthlySpendItem(**r) for r in mongo_result}
    return [
        by_month.get(m, MonthlySpendItem(month=m, total_ht=0, total_ttc=0, invoice_count=0, opex=0, capex=0))
        for m in months
    ]


# ── 2. Top 10 suppliers ────────────────────────────────────────────────────────

@analytics_router.get(
    "/by-supplier",
    response_model=list[SupplierSpendItem],
    summary="Top 10 fournisseurs par montant",
    description=(
        "Classement des 10 premiers fournisseurs par montant TTC total "
        "sur les factures traitées (statuts terminaux). SQL GROUP BY issuer_name."
    ),
)
async def by_supplier(
    year: int | None = Query(None, description="Filtrer par année (optionnel)"),
    _: dict = _DIRECTION_COMPTABLE,
):
    from src.storage.documents.service_bridge import by_supplier_mongo

    mongo_result = await by_supplier_mongo(year)
    if mongo_result is None:
        # Invoices are written Mongo-only (see CLAUDE.md) — the old SQLite
        # fallback here could only ever serve permanently stale data.
        _log.warning("by_supplier: MongoDB indisponible — retour d'une liste vide.")
        return []
    return [SupplierSpendItem(**r) for r in mongo_result]


# ── 3. Spending by PCE account ────────────────────────────────────────────────

@analytics_router.get(
    "/by-account",
    response_model=list[AccountSpendItem],
    summary="Dépenses par compte PCE",
    description=(
        "Répartition des dépenses par compte PCE tunisien (accounting_compte). "
        "Inclut le pourcentage du total pour chaque poste."
    ),
)
async def by_account(
    year: int | None = Query(None, description="Filtrer par année (optionnel)"),
    _: dict = _DIRECTION_COMPTABLE,
):
    from src.storage.documents.service_bridge import by_account_mongo

    mongo_result = await by_account_mongo(year)
    if mongo_result is None:
        # Invoices are written Mongo-only (see CLAUDE.md) — the old SQLite
        # fallback here could only ever serve permanently stale data.
        _log.warning("by_account: MongoDB indisponible — retour d'une liste vide.")
        return []
    return [AccountSpendItem(**r) for r in mongo_result]


# ── 4. Operational KPIs ───────────────────────────────────────────────────────

@analytics_router.get(
    "/kpis",
    response_model=AnalyticsKPIs,
    summary="KPIs opérationnels Direction",
    description=(
        "Métriques de performance : délai moyen de traitement (julianday), "
        "taux de rejet, taux de révision humaine, CAPEX/OPEX YTD et factures en attente."
    ),
)
async def analytics_kpis(
    year: int = Query(2026, description="Année fiscale"),
    _: dict = _DIRECTION_COMPTABLE,
):
    from src.storage.documents.service_bridge import analytics_kpis_mongo

    mongo_result = await analytics_kpis_mongo(year)
    if mongo_result is None:
        # Invoices are written Mongo-only (see CLAUDE.md) — the old SQLite
        # fallback here could only ever serve permanently stale data.
        _log.warning("analytics_kpis: MongoDB indisponible — retour de KPIs vides.")
        return AnalyticsKPIs(
            avg_processing_days=0.0, rejection_rate=0.0, human_review_rate=0.0,
            total_capex_ytd=0.0, total_opex_ytd=0.0, pending_count=0,
        )
    return AnalyticsKPIs(**mongo_result)
