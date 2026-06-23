"""Notification count endpoint — used by the frontend topbar badge."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps import get_session
from src.models.enums import InvoiceStatus
from src.storage.repository import InvoiceRepository

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationCountOut(BaseModel):
    count: int


@router.get("/count", response_model=NotificationCountOut)
def get_count(session: Session = Depends(get_session)):
    repo = InvoiceRepository(session)
    invoices = repo.list_all()
    count = sum(
        1 for inv in invoices
        if inv.human_review_required
        and inv.status not in (InvoiceStatus.REJECTED, InvoiceStatus.ERROR)
    )
    return NotificationCountOut(count=count)
