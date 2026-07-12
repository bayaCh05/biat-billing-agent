from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from src.models.enums import InvoiceStatus
from src.models.invoice import InvoiceRecord
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class AgeingBucket:
    current: float = 0.0      # not yet due
    days_1_30: float = 0.0
    days_31_60: float = 0.0
    days_61_90: float = 0.0
    over_90: float = 0.0

    @property
    def total_overdue(self) -> float:
        return self.days_1_30 + self.days_31_60 + self.days_61_90 + self.over_90

    @property
    def total(self) -> float:
        return self.current + self.total_overdue


@dataclass
class DashboardSnapshot:
    total_payables: float = 0.0         # outstanding supplier invoices (TND)
    total_receivables: float = 0.0      # outstanding client invoices (TND)
    payables_ageing: AgeingBucket = field(default_factory=AgeingBucket)
    receivables_ageing: AgeingBucket = field(default_factory=AgeingBucket)
    auto_approval_rate: float = 0.0     # % invoices that needed no human review
    invoices_by_status: dict[str, int] = field(default_factory=dict)
    overdue_count: int = 0
    flagged_count: int = 0


class Aggregator:
    """Produces payables/receivables dashboards and processing KPIs."""

    def __init__(self, repository) -> None:
        self.repository = repository

    def snapshot(self) -> DashboardSnapshot:
        snap = DashboardSnapshot()

        pending_payment = self.repository.get_pending_payment()
        pending_collection = self.repository.get_pending_collection()
        overdue = self.repository.get_overdue()
        flagged = self.repository.get_flagged()

        snap.total_payables = self._sum_amounts(pending_payment)
        snap.total_receivables = self._sum_amounts(pending_collection)
        snap.payables_ageing = self._build_ageing(pending_payment)
        snap.receivables_ageing = self._build_ageing(pending_collection)
        snap.overdue_count = len(overdue)
        snap.flagged_count = len(flagged)
        snap.auto_approval_rate = self._auto_approval_rate()
        snap.invoices_by_status = self._count_by_status()

        logger.info(
            "dashboard_snapshot",
            total_payables=snap.total_payables,
            total_receivables=snap.total_receivables,
            overdue_count=snap.overdue_count,
            flagged_count=snap.flagged_count,
        )
        return snap

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _sum_amounts(invoices: list[InvoiceRecord]) -> float:
        return sum(
            inv.amount_ttc.value
            for inv in invoices
            if inv.amount_ttc.value is not None
        )

    @staticmethod
    def _build_ageing(invoices: list[InvoiceRecord]) -> AgeingBucket:
        today = datetime.now(tz=timezone.utc).date()
        bucket = AgeingBucket()
        for inv in invoices:
            amount = inv.amount_ttc.value or 0.0
            due: date | None = inv.due_date.value
            if due is None:
                bucket.current += amount
                continue
            days_overdue = (today - due).days
            if days_overdue <= 0:
                bucket.current += amount
            elif days_overdue <= 30:
                bucket.days_1_30 += amount
            elif days_overdue <= 60:
                bucket.days_31_60 += amount
            elif days_overdue <= 90:
                bucket.days_61_90 += amount
            else:
                bucket.over_90 += amount
        return bucket

    _TERMINAL_STATUSES = [
        InvoiceStatus.EXPORTED,
        InvoiceStatus.PAID,
        InvoiceStatus.COLLECTED,
        InvoiceStatus.REJECTED,
    ]

    def _auto_approval_rate(self) -> float:
        """Fraction of terminal invoices that required no human review (2 SQL queries)."""
        total, auto = self.repository.count_auto_approved(self._TERMINAL_STATUSES)
        return round(auto / total, 4) if total > 0 else 0.0

    def _count_by_status(self) -> dict[str, int]:
        """Single GROUP BY query instead of one query per status."""
        return self.repository.count_by_status()
