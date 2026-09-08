"""Suivi (lifecycle tracking) endpoints — ageing, pending payments, overdue."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth import require_role
from api.schemas import InvoiceSummary

router = APIRouter(prefix="/suivi", tags=["analytics"])

_log = logging.getLogger(__name__)

# Mêmes rôles que la page Suivi côté frontend (Sidebar.tsx: roles: ['Comptable',
# 'Chef de Projet']) — auparavant ce routeur n'avait aucune restriction de rôle
# côté backend du tout. Direction/Admin ne voient pas ce lien dans la nav —
# ils ont leur propre vue équivalente via /kpi — donc ne pas les ajouter ici
# reproduirait l'intention déjà établie côté frontend plutôt que d'en créer une
# nouvelle incohérence dans l'autre sens.
_VIEW = Depends(require_role("Comptable", "Chef de Projet"))


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


@router.get(
    "/snapshot",
    response_model=SuiviSnapshotOut,
    summary="Snapshot de trésorerie",
    description=(
        "Retourne un instantané du suivi de trésorerie : "
        "total des payables fournisseurs et receivables clients, "
        "ageing en tranches (courant, 1–30, 31–60, 61–90, >90 jours), "
        "listes détaillées des factures en attente de paiement, de recouvrement et en retard."
    ),
    response_description="Snapshot complet avec buckets d'ageing et listes de factures",
    responses={403: {"description": "Rôle Comptable ou Chef de Projet requis"}},
)
async def get_snapshot(_: dict = _VIEW):
    from src.storage.documents.service_bridge import get_suivi_invoices_mongo

    today = datetime.now(tz=timezone.utc).date()

    mongo_result = await get_suivi_invoices_mongo()
    if mongo_result is None:
        # Invoices are written Mongo-only (see CLAUDE.md) — the old SQLite
        # fallback here could only ever serve permanently stale data.
        _log.warning("get_snapshot: MongoDB indisponible — retour d'un snapshot vide.")
        pending_payment, pending_collection, overdue = [], [], []
    else:
        pending_payment = mongo_result["pending_payment"]
        pending_collection = mongo_result["pending_collection"]
        overdue = mongo_result["overdue"]

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
