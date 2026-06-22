"""Review queue endpoints."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.deps import get_session
from api.schemas import InvoiceSummary, ReviewActionRequest
from src.models.enums import InvoiceStatus
from src.storage.repository import InvoiceRepository

router = APIRouter(prefix="/review", tags=["review"])


@router.get("", response_model=list[InvoiceSummary])
def get_review_queue(session: Session = Depends(get_session)):
    """Return all invoices requiring human review (FLAGGED or human_review_required=True)."""
    repo = InvoiceRepository(session)
    all_inv = repo.list_all(limit=500)
    queue = [
        inv for inv in all_inv
        if inv.human_review_required or inv.status == InvoiceStatus.FLAGGED
    ]
    return [InvoiceSummary.from_record(inv) for inv in queue]


@router.post("/{invoice_id}/approve")
def approve(
    invoice_id: str,
    body: ReviewActionRequest = ReviewActionRequest(),
    session: Session = Depends(get_session),
):
    repo = InvoiceRepository(session)
    inv = _get_or_404(repo, invoice_id)
    # Resolve all open flags
    for flag in inv.flags:
        if not flag.resolved:
            flag.resolved = True
            flag.resolved_by = "human"
    inv.human_review_required = False
    inv.human_review_notes = body.notes or None
    inv.status = InvoiceStatus.VALIDATED
    repo.save(inv)
    return {"id": invoice_id, "action": "approved", "new_status": inv.status.value}


@router.post("/{invoice_id}/reject")
def reject(
    invoice_id: str,
    body: ReviewActionRequest = ReviewActionRequest(),
    session: Session = Depends(get_session),
):
    repo = InvoiceRepository(session)
    inv = _get_or_404(repo, invoice_id)
    inv.status = InvoiceStatus.REJECTED
    inv.human_review_required = False
    inv.human_review_notes = body.notes or None
    repo.save(inv)
    return {"id": invoice_id, "action": "rejected", "new_status": inv.status.value}


def _get_or_404(repo: InvoiceRepository, invoice_id: str):
    try:
        uid = UUID(invoice_id)
    except ValueError:
        raise HTTPException(400, "Invalid UUID")
    inv = repo.get_by_id(uid)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    return inv
