"""Payment installments — list with joined invoice info + mark-paid."""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from api.auth import get_current_user, require_role
from api.deps import get_session

router = APIRouter(prefix="/payments", tags=["payments"])

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
def get_summary(session: Session = Depends(get_session), _=_VIEW):
    today = date.today()
    rows = session.execute(text(
        "SELECT status, base_amount, current_amount, due_date "
        "FROM payment_installments"
    )).fetchall()

    total = len(rows)
    late = [r for r in rows if r[0] == "LATE"]
    pending = [r for r in rows if r[0] == "PENDING"]
    paid = [r for r in rows if r[0] == "PAID"]
    total_penalties = sum((r[2] or 0) - (r[1] or 0) for r in late)

    # Next upcoming due (PENDING, not yet overdue)
    upcoming = [r for r in pending if r[3] and r[3] >= today.isoformat()]
    upcoming.sort(key=lambda r: r[3])
    next_due_date = upcoming[0][3] if upcoming else None
    next_due_amount = upcoming[0][2] if upcoming else None

    return InstallmentSummary(
        total=total,
        late_count=len(late),
        pending_count=len(pending),
        paid_count=len(paid),
        total_penalties=round(total_penalties, 3),
        next_due_date=next_due_date,
        next_due_amount=next_due_amount,
    )


@router.get("/installments", response_model=list[InstallmentOut])
def list_installments(
    status: list[str] = Query(default=[]),
    session: Session = Depends(get_session),
    _=_VIEW,
):
    today = date.today()

    rows = session.execute(text("""
        SELECT
            pi.id,
            pi.invoice_id,
            i.issuer_name,
            i.invoice_number,
            pi.installment_number,
            pi.total_installments,
            pi.base_amount,
            pi.current_amount,
            pi.due_date,
            pi.paid_date,
            pi.paid_amount,
            pi.status,
            pi.late_periods
        FROM payment_installments pi
        LEFT JOIN invoices i ON i.id = pi.invoice_id
        ORDER BY
            CASE pi.status WHEN 'LATE' THEN 0 WHEN 'PENDING' THEN 1 ELSE 2 END,
            pi.due_date ASC
    """)).fetchall()

    result = []
    for r in rows:
        (id_, inv_id, issuer, inv_num, num, total, base, current,
         due_str, paid_date, paid_amount, stat, late_periods) = r

        if status and stat not in status:
            continue

        due = date.fromisoformat(due_str) if due_str else today
        days_overdue = max(0, (today - due).days) if stat in ("LATE", "PENDING") else 0
        penalty = round((current or base) - base, 3)
        penalty_pct = round((penalty / base) * 100, 1) if base else 0.0

        result.append(InstallmentOut(
            id=str(id_),
            invoice_id=str(inv_id),
            issuer_name=issuer,
            invoice_number=inv_num,
            installment_number=num,
            total_installments=total,
            base_amount=round(base, 3),
            current_amount=round(current, 3),
            penalty_amount=round(penalty, 3),
            penalty_pct=penalty_pct,
            due_date=due_str,
            paid_date=paid_date,
            paid_amount=paid_amount,
            status=stat,
            late_periods=late_periods,
            days_overdue=days_overdue,
        ))

    return result


@router.patch("/installments/{installment_id}/mark-paid")
def mark_paid(
    installment_id: str,
    body: MarkPaidRequest,
    session: Session = Depends(get_session),
    _=_EDIT,
):
    from src.storage.orm_models_payments import PaymentInstallmentORM

    inst = session.get(PaymentInstallmentORM, UUID(installment_id))
    if not inst:
        raise HTTPException(404, "Échéance introuvable.")
    if inst.status == "PAID":
        raise HTTPException(400, "Échéance déjà marquée comme payée.")

    inst.status = "PAID"
    inst.paid_amount = body.paid_amount
    inst.paid_date = date.fromisoformat(body.paid_date)
    inst.updated_at = datetime.now(timezone.utc)
    session.commit()
    return {"id": installment_id, "status": "PAID", "paid_amount": body.paid_amount}
