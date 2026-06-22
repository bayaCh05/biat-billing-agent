"""KPI / dashboard metrics endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import get_session
from api.schemas import KpiOut
from src.storage.repository import InvoiceRepository
from src.models.enums import InvoiceStatus

router = APIRouter(prefix="/kpi", tags=["kpi"])

_TERMINAL = [InvoiceStatus.EXPORTED, InvoiceStatus.JOURNALED, InvoiceStatus.PAID, InvoiceStatus.COLLECTED]


@router.get("", response_model=KpiOut)
def get_kpi(session: Session = Depends(get_session)):
    repo = InvoiceRepository(session)
    invoices = repo.list_all()

    terminal_set = set(_TERMINAL)
    processed = [inv for inv in invoices if inv.status in terminal_set]

    total_amount = sum(inv.amount_ttc.value for inv in processed if inv.amount_ttc.value)
    flagged = [inv for inv in invoices if inv.status == InvoiceStatus.FLAGGED]
    pending = [inv for inv in invoices if inv.human_review_required and inv.status != InvoiceStatus.FLAGGED]

    total_processed, auto_approved = repo.count_auto_approved(statuses=_TERMINAL)
    total = max(len(invoices), 1)

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
