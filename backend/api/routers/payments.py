"""Payment installments — list with joined invoice info + mark-paid."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import require_role

router = APIRouter(prefix="/payments", tags=["payments"])
_log = logging.getLogger(__name__)

_VIEW = Depends(require_role("Comptable", "Direction", "Admin"))
_EDIT = Depends(require_role("Comptable", "Admin"))


# ── Response models ───────────────────────────────────────────────────────────

class InstallmentOut(BaseModel):
    id: str
    invoice_id: str
    issuer_name: str | None
    invoice_number: str | None
    installment_number: int
    total_installments: int
    base_amount: float
    current_amount: float
    penalty_amount: float
    penalty_pct: float
    due_date: str
    paid_date: str | None
    paid_amount: float | None
    status: str
    late_periods: int
    days_overdue: int


class InstallmentSummary(BaseModel):
    total: int
    late_count: int
    pending_count: int
    paid_count: int
    total_penalties: float
    next_due_date: str | None
    next_due_amount: float | None


class MarkPaidRequest(BaseModel):
    paid_amount: float
    paid_date: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/installments/summary", response_model=InstallmentSummary)
async def get_summary(_=_VIEW):
    from src.storage.documents.service_bridge import get_installments_summary_mongo

    mongo_result = await get_installments_summary_mongo()
    if mongo_result is None:
        # Payment installments are written Mongo-only (see CLAUDE.md) — the
        # old SQLite fallback here could only ever serve permanently stale data.
        _log.warning("get_summary: MongoDB indisponible — retour d'un résumé vide.")
        return InstallmentSummary(
            total=0, late_count=0, pending_count=0, paid_count=0,
            total_penalties=0.0, next_due_date=None, next_due_amount=None,
        )
    return InstallmentSummary(**mongo_result)


@router.get("/installments", response_model=list[InstallmentOut])
async def list_installments(
    status: list[str] = Query(default=[]),
    _=_VIEW,
):
    from src.storage.documents.service_bridge import list_installments_mongo

    mongo_result = await list_installments_mongo(status)
    if mongo_result is None:
        # Payment installments are written Mongo-only (see CLAUDE.md) — the
        # old SQLite fallback here could only ever serve permanently stale data.
        _log.warning("list_installments: MongoDB indisponible — retour d'une liste vide.")
        return []
    return [InstallmentOut(**r) for r in mongo_result]


@router.patch("/installments/{installment_id}/mark-paid")
async def mark_paid(
    installment_id: str,
    body: MarkPaidRequest,
    _=_EDIT,
):
    from src.storage.documents.service_bridge import mark_installment_paid_native

    _log.info("Marking installment paid: %s", installment_id)
    result = await mark_installment_paid_native(installment_id, body.paid_amount, body.paid_date)
    if result is None:
        raise HTTPException(404, "Échéance introuvable.")
    if result == "ALREADY_PAID":
        raise HTTPException(400, "Échéance déjà marquée comme payée.")
    return {"id": installment_id, "status": "PAID", "paid_amount": body.paid_amount}
