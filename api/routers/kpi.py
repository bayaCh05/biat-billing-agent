"""KPI and analytics endpoints for Direction / Comptable dashboards."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from api.auth import require_role
from api.deps import get_session
from api.schemas import KpiOut
from src.models.enums import InvoiceStatus
from src.storage.repository import InvoiceRepository

router = APIRouter(prefix="/kpi", tags=["analytics"])
analytics_router = APIRouter(prefix="/analytics", tags=["analytics"])

_TERMINAL = [InvoiceStatus.EXPORTED, InvoiceStatus.JOURNALED, InvoiceStatus.PAID, InvoiceStatus.COLLECTED]
_TERMINAL_STR = {"EXPORTED", "JOURNALED", "PAID", "COLLECTED"}
_DIRECTION_COMPTABLE = Depends(require_role("Admin", "Direction", "Comptable"))


# ── Existing KPI endpoint (no role change — already protected by global middleware) ──

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
def get_kpi(session: Session = Depends(get_session)):
    repo = InvoiceRepository(session)
    invoices = repo.list_all()

    terminal_set = set(_TERMINAL)
    processed = [inv for inv in invoices if inv.status in terminal_set]

    total_amount = sum(inv.amount_ttc.value for inv in processed if inv.amount_ttc.value)
    flagged = [inv for inv in invoices if inv.status == InvoiceStatus.FLAGGED]
    pending = [inv for inv in invoices if inv.human_review_required and inv.status != InvoiceStatus.FLAGGED]

    total_processed, auto_approved = repo.count_auto_approved(statuses=_TERMINAL)

    by_status: dict[str, int] = {}
    for inv in invoices:
        key = inv.status.value
        by_status[key] = by_status.get(key, 0) + 1

    return KpiOut(
        total_invoices=len(invoices),
        total_amount_ttc=total_amount,
        auto_approved=auto_approved,
        auto_approval_rate=round(auto_approved / max(total_processed, 1) * 100, 1),
        flagged=len(flagged),
        pending_review=len(pending),
        by_status=by_status,
    )


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
def monthly_spend(
    year: int = Query(2026, description="Année fiscale"),
    _: dict = _DIRECTION_COMPTABLE,
    session: Session = Depends(get_session),
):
    from src.storage.orm_models import InvoiceORM

    rows = session.execute(
        select(
            func.strftime("%Y-%m", InvoiceORM.invoice_date).label("ym"),
            func.sum(InvoiceORM.amount_ht).label("total_ht"),
            func.sum(InvoiceORM.amount_ttc).label("total_ttc"),
            func.count(InvoiceORM.id).label("cnt"),
            func.sum(
                case((InvoiceORM.charge_type == "OPEX", InvoiceORM.amount_ht), else_=0)
            ).label("opex"),
            func.sum(
                case((InvoiceORM.charge_type == "CAPEX", InvoiceORM.amount_ht), else_=0)
            ).label("capex"),
        )
        .where(
            func.strftime("%Y", InvoiceORM.invoice_date) == str(year),
            InvoiceORM.status.in_(_TERMINAL_STR),
            InvoiceORM.direction == "SUPPLIER",
        )
        .group_by(func.strftime("%Y-%m", InvoiceORM.invoice_date))
        .order_by(func.strftime("%Y-%m", InvoiceORM.invoice_date))
    ).all()

    by_month: dict[str, MonthlySpendItem] = {}
    for row in rows:
        by_month[row.ym] = MonthlySpendItem(
            month=row.ym,
            total_ht=round(float(row.total_ht or 0), 3),
            total_ttc=round(float(row.total_ttc or 0), 3),
            invoice_count=int(row.cnt),
            opex=round(float(row.opex or 0), 3),
            capex=round(float(row.capex or 0), 3),
        )

    months = [f"{year}-{m:02d}" for m in range(1, 13)]
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
def by_supplier(
    year: int | None = Query(None, description="Filtrer par année (optionnel)"),
    _: dict = _DIRECTION_COMPTABLE,
    session: Session = Depends(get_session),
):
    from src.storage.orm_models import InvoiceORM

    stmt = (
        select(
            InvoiceORM.issuer_name.label("supplier"),
            func.sum(InvoiceORM.amount_ttc).label("total_ttc"),
            func.sum(InvoiceORM.amount_ht).label("total_ht"),
            func.count(InvoiceORM.id).label("cnt"),
        )
        .where(
            InvoiceORM.status.in_(_TERMINAL_STR),
            InvoiceORM.direction == "SUPPLIER",
            InvoiceORM.issuer_name.isnot(None),
        )
        .group_by(InvoiceORM.issuer_name)
        .order_by(func.sum(InvoiceORM.amount_ttc).desc())
        .limit(10)
    )
    if year:
        stmt = stmt.where(func.strftime("%Y", InvoiceORM.invoice_date) == str(year))

    rows = session.execute(stmt).all()
    return [
        SupplierSpendItem(
            supplier=row.supplier or "Inconnu",
            total_ttc=round(float(row.total_ttc or 0), 3),
            total_ht=round(float(row.total_ht or 0), 3),
            count=int(row.cnt),
        )
        for row in rows
    ]


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
def by_account(
    year: int | None = Query(None, description="Filtrer par année (optionnel)"),
    _: dict = _DIRECTION_COMPTABLE,
    session: Session = Depends(get_session),
):
    from src.storage.orm_models import InvoiceORM

    stmt = (
        select(
            InvoiceORM.accounting_compte.label("compte"),
            InvoiceORM.accounting_label.label("label"),
            func.sum(InvoiceORM.amount_ht).label("total_ht"),
        )
        .where(
            InvoiceORM.status.in_(_TERMINAL_STR),
            InvoiceORM.direction == "SUPPLIER",
            InvoiceORM.accounting_compte.isnot(None),
        )
        .group_by(InvoiceORM.accounting_compte, InvoiceORM.accounting_label)
        .order_by(func.sum(InvoiceORM.amount_ht).desc())
    )
    if year:
        stmt = stmt.where(func.strftime("%Y", InvoiceORM.invoice_date) == str(year))

    rows = session.execute(stmt).all()
    grand_total = sum(float(r.total_ht or 0) for r in rows) or 1.0

    return [
        AccountSpendItem(
            compte=row.compte or "",
            label=row.label or row.compte or "",
            total_ht=round(float(row.total_ht or 0), 3),
            pct=round(float(row.total_ht or 0) / grand_total * 100, 1),
        )
        for row in rows
    ]


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
def analytics_kpis(
    year: int = Query(2026, description="Année fiscale"),
    _: dict = _DIRECTION_COMPTABLE,
    session: Session = Depends(get_session),
):
    from src.storage.orm_models import InvoiceORM

    year_filter = func.strftime("%Y", InvoiceORM.invoice_date) == str(year)

    # Average processing time (received → exported) in days using SQLite julianday
    proc_row = session.execute(
        select(
            func.avg(
                func.julianday(InvoiceORM.exported_at) - func.julianday(InvoiceORM.received_at)
            ).label("avg_days")
        )
        .where(
            InvoiceORM.exported_at.isnot(None),
            InvoiceORM.received_at.isnot(None),
            InvoiceORM.direction == "SUPPLIER",
        )
    ).first()
    avg_days = round(float(proc_row.avg_days or 0), 1)

    # Total & rejection rate
    count_row = session.execute(
        select(
            func.count(InvoiceORM.id).label("total"),
            func.sum(case((InvoiceORM.status == "REJECTED", 1), else_=0)).label("rejected"),
            func.sum(case((InvoiceORM.human_review_required == True, 1), else_=0)).label("reviewed"),  # noqa: E712
        )
        .where(year_filter, InvoiceORM.direction == "SUPPLIER")
    ).first()
    total = int(count_row.total or 1)
    rejection_rate = round(int(count_row.rejected or 0) / total * 100, 1)
    human_review_rate = round(int(count_row.reviewed or 0) / total * 100, 1)

    # CAPEX / OPEX YTD
    capex_opex_row = session.execute(
        select(
            func.sum(
                case((InvoiceORM.charge_type == "CAPEX", InvoiceORM.amount_ht), else_=0)
            ).label("capex"),
            func.sum(
                case((InvoiceORM.charge_type == "OPEX", InvoiceORM.amount_ht), else_=0)
            ).label("opex"),
        )
        .where(
            year_filter,
            InvoiceORM.status.in_(_TERMINAL_STR),
            InvoiceORM.direction == "SUPPLIER",
        )
    ).first()
    total_capex = round(float(capex_opex_row.capex or 0), 3)
    total_opex = round(float(capex_opex_row.opex or 0), 3)

    # Pending (not yet journaled)
    pending_row = session.execute(
        select(func.count(InvoiceORM.id))
        .where(
            InvoiceORM.status.not_in(_TERMINAL_STR),
            InvoiceORM.status.not_in({"REJECTED", "ERROR", "EXTRACTION_FAILED", "ESCALATED"}),
            InvoiceORM.direction == "SUPPLIER",
        )
    ).scalar()
    pending_count = int(pending_row or 0)

    return AnalyticsKPIs(
        avg_processing_days=avg_days,
        rejection_rate=rejection_rate,
        human_review_rate=human_review_rate,
        total_capex_ytd=total_capex,
        total_opex_ytd=total_opex,
        pending_count=pending_count,
    )
