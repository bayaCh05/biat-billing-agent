"""Review queue endpoints."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from api.auth import get_current_user, require_role
from api.deps import get_session
from api.schemas import InvoiceSummary, ReviewActionRequest, ActionResultOut
from src.models.audit import AuditLogCreate
from src.models.enums import InvoiceStatus
from src.services.audit_service import log_action, _ip, _ua
from src.storage.repository import InvoiceRepository

router = APIRouter(prefix="/review", tags=["invoices"])

_COMPTABLE_OR_ADMIN = Depends(require_role("Comptable", "Admin"))


@router.get(
    "",
    response_model=list[InvoiceSummary],
    summary="File de révision humaine",
    description=(
        "Retourne toutes les factures nécessitant une intervention humaine : "
        "statut FLAGGED ou champ `human_review_required=true`. "
        "Triées par date de réception ascendante (FIFO)."
    ),
    response_description="Liste de factures en attente de décision (approuver ou rejeter)",
)
def get_review_queue(session: Session = Depends(get_session)):
    repo = InvoiceRepository(session)
    all_inv = repo.list_all(limit=500)
    queue = [
        inv for inv in all_inv
        if inv.human_review_required or inv.status == InvoiceStatus.FLAGGED
    ]
    return [InvoiceSummary.from_record(inv) for inv in queue]


@router.post(
    "/{invoice_id}/approve",
    response_model=ActionResultOut,
    summary="Approuver une facture",
    description=(
        "Approuve une facture FLAGGED : résout tous les flags ouverts, "
        "marque `human_review_required=false` et bascule le statut vers VALIDATED. "
        "Un champ `notes` optionnel est enregistré pour la piste d'audit."
    ),
    response_description="Confirmation avec nouveau statut VALIDATED",
    responses={404: {"description": "Facture non trouvée"}},
)
def approve(
    invoice_id: str,
    request: Request,
    body: ReviewActionRequest = ReviewActionRequest(),
    current_user: dict = Depends(get_current_user),
    _: None = _COMPTABLE_OR_ADMIN,
    session: Session = Depends(get_session),
):
    repo = InvoiceRepository(session)
    inv = _get_or_404(repo, invoice_id)
    for flag in inv.flags:
        if not flag.resolved:
            flag.resolved = True
            flag.resolved_by = "human"
    inv.human_review_required = False
    inv.human_review_notes = body.notes or None
    inv.status = InvoiceStatus.VALIDATED
    repo.save(inv)

    log_action(session, AuditLogCreate(
        user_id=current_user.get("sub"),
        user_email=current_user.get("email"),
        user_role=current_user.get("role"),
        action="APPROVE",
        resource_type="InvoiceRecord",
        resource_id=invoice_id,
        status="SUCCESS",
        detail=body.notes or None,
        ip_address=_ip(request),
        user_agent=_ua(request),
    ))
    session.commit()
    return ActionResultOut(id=invoice_id, action="approved", new_status=inv.status.value)


@router.post(
    "/{invoice_id}/reject",
    response_model=ActionResultOut,
    summary="Rejeter une facture",
    description=(
        "Rejette définitivement une facture : statut → REJECTED, `human_review_required=false`. "
        "La facture est retirée du pipeline mais conservée en base pour historique."
    ),
    response_description="Confirmation avec nouveau statut REJECTED",
    responses={404: {"description": "Facture non trouvée"}},
)
def reject(
    invoice_id: str,
    request: Request,
    body: ReviewActionRequest = ReviewActionRequest(),
    current_user: dict = Depends(get_current_user),
    _: None = _COMPTABLE_OR_ADMIN,
    session: Session = Depends(get_session),
):
    repo = InvoiceRepository(session)
    inv = _get_or_404(repo, invoice_id)
    inv.status = InvoiceStatus.REJECTED
    inv.human_review_required = False
    inv.human_review_notes = body.notes or None
    repo.save(inv)

    log_action(session, AuditLogCreate(
        user_id=current_user.get("sub"),
        user_email=current_user.get("email"),
        user_role=current_user.get("role"),
        action="REJECT",
        resource_type="InvoiceRecord",
        resource_id=invoice_id,
        status="SUCCESS",
        detail=body.notes or None,
        ip_address=_ip(request),
        user_agent=_ua(request),
    ))
    session.commit()
    return ActionResultOut(id=invoice_id, action="rejected", new_status=inv.status.value)


def _get_or_404(repo: InvoiceRepository, invoice_id: str):
    try:
        uid = UUID(invoice_id)
    except ValueError:
        raise HTTPException(400, "Invalid UUID")
    inv = repo.get_by_id(uid)
    if not inv:
        raise HTTPException(404, "Invoice not found")
    return inv
