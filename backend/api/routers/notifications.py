"""Notification endpoints — DB-persisted notifications with mark-as-read support."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps import get_session
from src.storage.orm_models_notifications import NotificationORM

router = APIRouter(prefix="/notifications", tags=["notifications"])

_log = logging.getLogger(__name__)


class NotificationOut(BaseModel):
    id: str
    type: str
    title: str
    body: str
    is_read: bool
    created_at: str
    invoice_id: str | None


class NotificationCountOut(BaseModel):
    count: int


def _to_out(n: NotificationORM) -> NotificationOut:
    return NotificationOut(
        id=str(n.id),
        type=n.type,
        title=n.title,
        body=n.body,
        is_read=n.is_read,
        created_at=n.created_at.isoformat(),
        invoice_id=str(n.invoice_id) if n.invoice_id else None,
    )


@router.get(
    "/count",
    response_model=NotificationCountOut,
    summary="Nombre de notifications non lues",
    description=(
        "Retourne le compteur de notifications non lues. "
        "Appelé par la cloche de notification dans la barre supérieure. "
        "Déclenche aussi la synchronisation des factures FLAGGED en attente."
    ),
    response_description="Compteur de notifications non lues",
)
async def get_count(session: Session = Depends(get_session)):
    from src.storage.documents.service_bridge import (
        count_unread_notifications_mongo, sync_flagged_invoices_mirrored,
    )

    await sync_flagged_invoices_mirrored(session)
    mongo_count = await count_unread_notifications_mongo()
    if mongo_count is None:
        # Notifications are written Mongo-only (see CLAUDE.md) — the old
        # SQLite fallback here could only ever serve permanently stale data.
        _log.warning("get_count: MongoDB indisponible — retour d'un compteur à 0.")
        return NotificationCountOut(count=0)
    return NotificationCountOut(count=mongo_count)


@router.get(
    "/list",
    response_model=list[NotificationOut],
    summary="Lister les notifications",
    description=(
        "Retourne toutes les notifications persistées en base de données. "
        "Les non-lues apparaissent en premier, puis par date décroissante. "
        "Types : INVOICE_FLAGGED, INVOICE_ESCALATED, PAYMENT_OVERDUE, BUDGET_EXCEEDED."
    ),
    response_description="Liste de notifications avec statut de lecture",
)
async def list_notifications(session: Session = Depends(get_session)):
    from src.storage.documents.service_bridge import (
        list_notifications_mongo, sync_flagged_invoices_mirrored,
    )

    await sync_flagged_invoices_mirrored(session)
    mongo_rows = await list_notifications_mongo()
    if mongo_rows is None:
        _log.warning("list_notifications: MongoDB indisponible — retour d'une liste vide.")
        return []
    return [_to_out(n) for n in mongo_rows]


@router.patch(
    "/{notif_id}/read",
    response_model=NotificationOut,
    summary="Marquer une notification comme lue",
    description="Passe `is_read=true` sur une notification spécifique.",
    response_description="Notification mise à jour avec is_read=true",
    responses={404: {"description": "Notification non trouvée"}},
)
async def mark_read(notif_id: str):
    from src.storage.documents.service_bridge import mark_notification_read_native

    notif = await mark_notification_read_native(notif_id)
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found.")
    return _to_out(notif)


@router.post(
    "/read-all",
    response_model=NotificationCountOut,
    summary="Tout marquer comme lu",
    description="Marque toutes les notifications non lues comme lues en une seule opération.",
    response_description="Compteur remis à zéro (count=0)",
)
async def mark_all_read():
    from src.storage.documents.service_bridge import mark_all_notifications_read_native

    await mark_all_notifications_read_native()
    return NotificationCountOut(count=0)
