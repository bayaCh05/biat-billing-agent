"""Review queue endpoints."""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.auth import get_current_user, require_role
from api.deps import get_session
from api.schemas import InvoiceSummary, ReviewActionRequest, ActionResultOut
from src.storage.repository import InvoiceRepository

router = APIRouter(prefix="/review", tags=["invoices"])

_log = logging.getLogger(__name__)

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
async def get_review_queue(session: Session = Depends(get_session)):
    from src.storage.documents.service_bridge import get_review_queue_mongo

    mongo_queue = await get_review_queue_mongo()
    if mongo_queue is not None:
        return [InvoiceSummary.from_record(inv) for inv in mongo_queue]

    # The headless daemon this fallback originally guarded against (an invoice
    # written SQLite-only by scripts/run_agent.py) was deleted in Lot B
    # (2026-07) — no code path can write a new SQLite-only invoice anymore.
    # Kept anyway (re-verified 2026-07-15, see CLAUDE.md "Lot 10"): any
    # invoice flagged for review *before* that deletion still only exists in
    # SQLite, and dropping this fallback would make those old rows silently
    # disappear from the queue rather than just going unreachable when Mongo
    # is down. Logged so the trigger is at least visible instead of silent.
    _log.warning(
        "get_review_queue: MongoDB indisponible — repli sur la file de révision SQLite."
    )
    repo = InvoiceRepository(session)
    queue = repo.get_review_queue()
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
async def approve(
    invoice_id: str,
    body: ReviewActionRequest = ReviewActionRequest(),
    current_user: dict = Depends(get_current_user),
    _: None = _COMPTABLE_OR_ADMIN,
):
    from src.storage.documents.service_bridge import approve_invoice_native

    try:
        UUID(invoice_id)
    except ValueError:
        raise HTTPException(400, "Invalid UUID")

    doc = await approve_invoice_native(invoice_id, body.notes or None, current_user)
    if doc is None:
        raise HTTPException(404, "Invoice not found")

    return ActionResultOut(id=invoice_id, action="approved", new_status=doc.status)


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
async def reject(
    invoice_id: str,
    body: ReviewActionRequest = ReviewActionRequest(),
    current_user: dict = Depends(get_current_user),
    _: None = _COMPTABLE_OR_ADMIN,
):
    from src.storage.documents.service_bridge import reject_invoice_native

    try:
        UUID(invoice_id)
    except ValueError:
        raise HTTPException(400, "Invalid UUID")

    doc = await reject_invoice_native(invoice_id, body.notes or None, current_user)
    if doc is None:
        raise HTTPException(404, "Invoice not found")

    return ActionResultOut(id=invoice_id, action="rejected", new_status=doc.status)
