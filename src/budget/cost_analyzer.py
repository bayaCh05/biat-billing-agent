"""Cost analyzer — trend detection and anomaly flagging.

Operates on actual invoice data from the DB to identify:
  - Monthly spending trends per catalog category (TrendPoint series)
  - Anomalies: spending > threshold * historical_average for the same category/month
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from src.utils.date_utils import last_day_of_month as _last_day
from sqlalchemy import select, and_, func, extract

from src.storage.orm_models import InvoiceORM


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class TrendPoint:
    year: int
    month: int
    catalog_id: str
    label: str
    amount: float
    invoice_count: int

    @property
    def period_label(self) -> str:
        return f"{self.year}-{self.month:02d}"


@dataclass
class Anomaly:
    catalog_id: str
    label: str
    year: int
    month: int
    amount: float
    historical_avg: float
    ratio: float                # amount / historical_avg
    severity: str               # "warning" | "critical"
    invoice_count: int

    @property
    def excess_amount(self) -> float:
        return round(self.amount - self.historical_avg, 2)


# ── Analyzer ──────────────────────────────────────────────────────────────────

class CostAnalyzer:
    """Reads validated supplier invoices and surfaces trends + anomalies.

    Args:
        session:             SQLAlchemy session
        warning_ratio:       flag as warning when actual ≥ avg * this ratio (default 1.5 = +50%)
        critical_ratio:      flag as critical when actual ≥ avg * this ratio (default 2.0 = +100%)
        min_history_months:  minimum months of history needed before flagging anomalies
    """

    ACTUAL_STATUSES = ("VALIDATED", "EXPORTED", "PAID", "JOURNALED")

    def __init__(
        self,
        session: Session,
        warning_ratio: float = 1.5,
        critical_ratio: float = 2.0,
        min_history_months: int = 3,
    ) -> None:
        self.session = session
        self.warning_ratio = warning_ratio
        self.critical_ratio = critical_ratio
        self.min_history_months = min_history_months

    # ── Public API ────────────────────────────────────────────────────────────

    def trends(
        self,
        catalog_id: Optional[str] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        catalog_labels: Optional[dict[str, str]] = None,
    ) -> list[TrendPoint]:
        """Monthly spending trend, optionally filtered to one catalog category.

        catalog_labels: dict mapping catalog_id → label (for display purposes).
        """
        from_date = from_date or date(date.today().year - 1, 1, 1)
        to_date = to_date or date.today()

        stmt = (
            select(
                extract("year", InvoiceORM.invoice_date).label("yr"),
                extract("month", InvoiceORM.invoice_date).label("mo"),
                InvoiceORM.cost_catalog_id,
                func.sum(InvoiceORM.amount_ht).label("total"),
                func.count(InvoiceORM.id).label("cnt"),
            )
            .where(
                and_(
                    InvoiceORM.status.in_(self.ACTUAL_STATUSES),
                    InvoiceORM.direction == "SUPPLIER",
                    InvoiceORM.invoice_date >= from_date,
                    InvoiceORM.invoice_date <= to_date,
                    InvoiceORM.cost_catalog_id.isnot(None),
                    InvoiceORM.amount_ht.isnot(None),
                )
            )
            .group_by(
                extract("year", InvoiceORM.invoice_date),
                extract("month", InvoiceORM.invoice_date),
                InvoiceORM.cost_catalog_id,
            )
            .order_by("yr", "mo", InvoiceORM.cost_catalog_id)
        )

        if catalog_id:
            stmt = stmt.where(InvoiceORM.cost_catalog_id == catalog_id)

        rows = self.session.execute(stmt).all()
        labels = catalog_labels or {}

        return [
            TrendPoint(
                year=int(row.yr),
                month=int(row.mo),
                catalog_id=row.cost_catalog_id,
                label=labels.get(row.cost_catalog_id, row.cost_catalog_id),
                amount=round(float(row.total or 0), 2),
                invoice_count=int(row.cnt),
            )
            for row in rows
        ]

    def anomalies(
        self,
        year: int,
        month: int,
        catalog_labels: Optional[dict[str, str]] = None,
    ) -> list[Anomaly]:
        """Detect spending anomalies for a given month vs historical average.

        Historical average is computed from the same category over the
        previous N months (N = min_history_months..12).
        """
        current_actuals = self._monthly_actuals(year, month)
        if not current_actuals:
            return []

        labels = catalog_labels or {}
        found: list[Anomaly] = []

        for catalog_id, (amount, inv_count) in current_actuals.items():
            history = self._historical_monthly(catalog_id, year, month)
            if len(history) < self.min_history_months:
                continue

            avg = sum(history) / len(history)
            if avg == 0:
                continue

            ratio = amount / avg
            if ratio >= self.critical_ratio:
                severity = "critical"
            elif ratio >= self.warning_ratio:
                severity = "warning"
            else:
                continue

            found.append(Anomaly(
                catalog_id=catalog_id,
                label=labels.get(catalog_id, catalog_id),
                year=year,
                month=month,
                amount=round(amount, 2),
                historical_avg=round(avg, 2),
                ratio=round(ratio, 2),
                severity=severity,
                invoice_count=inv_count,
            ))

        return sorted(found, key=lambda a: a.ratio, reverse=True)

    def top_categories(
        self,
        year: int,
        through_month: int,
        top_n: int = 10,
        catalog_labels: Optional[dict[str, str]] = None,
    ) -> list[dict]:
        """Top N spending categories YTD, sorted by total amount descending."""
        start = date(year, 1, 1)
        end = _last_day(year, through_month)

        rows = self.session.execute(
            select(
                InvoiceORM.cost_catalog_id,
                func.sum(InvoiceORM.amount_ht).label("total"),
                func.count(InvoiceORM.id).label("cnt"),
            )
            .where(
                and_(
                    InvoiceORM.status.in_(self.ACTUAL_STATUSES),
                    InvoiceORM.direction == "SUPPLIER",
                    InvoiceORM.invoice_date >= start,
                    InvoiceORM.invoice_date <= end,
                    InvoiceORM.cost_catalog_id.isnot(None),
                    InvoiceORM.amount_ht.isnot(None),
                )
            )
            .group_by(InvoiceORM.cost_catalog_id)
            .order_by(func.sum(InvoiceORM.amount_ht).desc())
            .limit(top_n)
        ).all()

        labels = catalog_labels or {}
        grand_total = sum(float(r.total or 0) for r in rows) or 1.0

        return [
            {
                "catalog_id": row.cost_catalog_id,
                "label": labels.get(row.cost_catalog_id, row.cost_catalog_id),
                "total": round(float(row.total or 0), 2),
                "invoice_count": int(row.cnt),
                "pct_of_total": round(float(row.total or 0) / grand_total * 100, 1),
            }
            for row in rows
        ]

    # ── Internal ──────────────────────────────────────────────────────────────

    def _monthly_actuals(self, year: int, month: int) -> dict[str, tuple[float, int]]:
        """Returns {catalog_id: (amount_ht_sum, invoice_count)} for the given month."""
        start = date(year, month, 1)
        end = _last_day(year, month)

        rows = self.session.execute(
            select(
                InvoiceORM.cost_catalog_id,
                func.sum(InvoiceORM.amount_ht).label("total"),
                func.count(InvoiceORM.id).label("cnt"),
            )
            .where(
                and_(
                    InvoiceORM.status.in_(self.ACTUAL_STATUSES),
                    InvoiceORM.direction == "SUPPLIER",
                    InvoiceORM.invoice_date >= start,
                    InvoiceORM.invoice_date <= end,
                    InvoiceORM.cost_catalog_id.isnot(None),
                    InvoiceORM.amount_ht.isnot(None),
                )
            )
            .group_by(InvoiceORM.cost_catalog_id)
        ).all()

        return {
            row.cost_catalog_id: (float(row.total or 0), int(row.cnt))
            for row in rows
        }

    def _historical_monthly(
        self, catalog_id: str, ref_year: int, ref_month: int, lookback: int = 12
    ) -> list[float]:
        """Monthly totals for catalog_id over the lookback months before ref_year/ref_month."""
        end = _last_day(ref_year, ref_month)
        # go back 'lookback' months from the month before ref_month
        start_year, start_month = _subtract_months(ref_year, ref_month - 1, lookback)
        start = date(start_year, start_month, 1)

        rows = self.session.execute(
            select(
                extract("year", InvoiceORM.invoice_date).label("yr"),
                extract("month", InvoiceORM.invoice_date).label("mo"),
                func.sum(InvoiceORM.amount_ht).label("total"),
            )
            .where(
                and_(
                    InvoiceORM.status.in_(self.ACTUAL_STATUSES),
                    InvoiceORM.direction == "SUPPLIER",
                    InvoiceORM.cost_catalog_id == catalog_id,
                    InvoiceORM.invoice_date >= start,
                    InvoiceORM.invoice_date < date(ref_year, ref_month, 1),
                    InvoiceORM.amount_ht.isnot(None),
                )
            )
            .group_by("yr", "mo")
        ).all()

        return [float(row.total or 0) for row in rows]




def _subtract_months(year: int, month: int, n: int) -> tuple[int, int]:
    """Subtract n months from (year, month), clamping month to 1-12."""
    total = (year * 12 + month) - n
    y, m = divmod(total, 12)
    if m == 0:
        m = 12
        y -= 1
    return y, m
