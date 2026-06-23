"""Suivi (lifecycle tracking) endpoints — ageing, pending payments, overdue."""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps import get_session
from api.schemas import InvoiceSummary
from src.storage.repository import InvoiceRepository

router = APIRouter(prefix="/suivi", tags=["suivi"])


class AgeingBucketOut(BaseModel):
    current: float = 0.0
    days_1_30: float = 0.0
    days_31_60: float = 0.0
    days_61_90: float = 0.0
    over_90: float = 0.0
    count_current: int = 0
    count_1_30: int = 0
    count_31_60: int = 0
    count_61_90: int = 0
    count_over_90: int = 0


class SuiviSnapshotOut(BaseModel):
    total_payables: float
    total_receivables: float
    overdue_count: int
    pending_payment_count: int
    pending_collection_count: int
    payables_ageing: AgeingBucketOut
    receivables_ageing: AgeingBucketOut
    pending_payment: list[InvoiceSummary]
    pending_collection: list[InvoiceSummary]
    overdue: list[InvoiceSummary]


def _build_ageing(invoices, today: date) -> AgeingBucketOut:
    bucket = AgeingBucketOut()
    for inv in invoices:
        amount = inv.amount_ttc.value or 0.0
        # Ageing = days past due (negative = not yet due → current bucket)
        due = inv.due_date.value if inv.due_date and inv.due_date.value else None
        age_days = (today - due).days if due else 0

        if age_days <= 0:
            bucket.current += amount
            bucket.count_current += 1
        elif age_days <= 30:
            bucket.days_1_30 += amount
            bucket.count_1_30 += 1
        elif age_days <= 60:
            bucket.days_31_60 += amount
            bucket.count_31_60 += 1
        elif age_days <= 90:
            bucket.days_61_90 += amount
            bucket.count_61_90 += 1
        else:
            bucket.over_90 += amount
            bucket.count_over_90 += 1
    return bucket


@router.get("/snapshot", response_model=SuiviSnapshotOut)
def get_snapshot(session: Session = Depends(get_session)):
    repo = InvoiceRepository(session)
    today = datetime.now(tz=timezone.utc).date()

    pending_payment = repo.get_pending_payment()
    pending_collection = repo.get_pending_collection()
    overdue = repo.get_overdue()

    total_payables = sum(inv.amount_ttc.value or 0 for inv in pending_payment)
    total_receivables = sum(inv.amount_ttc.value or 0 for inv in pending_collection)

    return SuiviSnapshotOut(
        total_payables=total_payables,
        total_receivables=total_receivables,
        overdue_count=len(overdue),
        pending_payment_count=len(pending_payment),
        pending_collection_count=len(pending_collection),
        payables_ageing=_build_ageing(pending_payment, today),
        receivables_ageing=_build_ageing(pending_collection, today),
        pending_payment=[InvoiceSummary.from_record(i) for i in pending_payment],
        pending_collection=[InvoiceSummary.from_record(i) for i in pending_collection],
        overdue=[InvoiceSummary.from_record(i) for i in overdue],
    )
