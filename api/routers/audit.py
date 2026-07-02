"""Audit log endpoints — append-only compliance trail (BCT Circulaire 2025-13)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import require_role
from api.deps import get_session
from api.security.audit_integrity import compute_row_hash, verify_row_hash
from src.models.audit import AuditLogCreate, AuditLogOut
from src.services.audit_service import log_action, _ip, _ua
from src.storage.orm_models_audit import AuditLogORM

router = APIRouter(prefix="/audit", tags=["admin"])

_ALLOWED = Depends(require_role("Admin", "Direction"))


def _to_out(r: AuditLogORM) -> AuditLogOut:
    return AuditLogOut(
        id=str(r.id),
        created_at=r.created_at.isoformat(),
        user_id=r.user_id,
        user_email=r.user_email or r.actor or None,
        user_role=r.user_role,
        action=r.action,
        resource_type=r.resource_type,
        resource_id=r.resource_id or r.entity_id,
        before_value=r.before_value,
        after_value=r.after_value,
        ip_address=r.ip_address,
        user_agent=r.user_agent,
        status=r.status,
        detail=r.detail,
    )


@router.get(
    "/logs",
    response_model=list[AuditLogOut],
    summary="Journal d'audit complet",
    description=(
        "Retourne les entrées du journal d'audit BCT avec filtres et pagination. "
        "Piste d'audit inaltérable (append-only) — aucun endpoint DELETE n'existe. "
        "Réservé aux rôles Admin et Direction."
    ),
    response_description="Entrées d'audit triées par date décroissante",
)
def list_audit_logs(
    action: str | None = Query(None, description="Filtrer par action (LOGIN, CREATE, APPROVE, REJECT, UPDATE, DELETE, EXPORT)"),
    resource_type: str | None = Query(None, description="Filtrer par type de ressource (InvoiceRecord, Asset, User, JournalEntry)"),
    user_id: str | None = Query(None, description="Filtrer par ID utilisateur"),
    user_email: str | None = Query(None, description="Filtrer par email (partiel)"),
    status: str | None = Query(None, description="Filtrer par statut (SUCCESS, FAILURE)"),
    from_date: str | None = Query(None, description="Date de début ISO 8601 (ex: 2026-01-01)"),
    to_date: str | None = Query(None, description="Date de fin ISO 8601 (ex: 2026-12-31)"),
    limit: int = Query(100, ge=1, le=500, description="Nombre maximum d'entrées"),
    offset: int = Query(0, ge=0, description="Décalage pour la pagination"),
    _: dict = _ALLOWED,
    session: Session = Depends(get_session),
):
    stmt = select(AuditLogORM).order_by(AuditLogORM.created_at.desc())

    if action:
        stmt = stmt.where(AuditLogORM.action == action.upper())
    if resource_type:
        stmt = stmt.where(AuditLogORM.resource_type == resource_type)
    if user_id:
        stmt = stmt.where(AuditLogORM.user_id == user_id)
    if user_email:
        stmt = stmt.where(
            (AuditLogORM.user_email.ilike(f"%{user_email}%")) |
            (AuditLogORM.actor.ilike(f"%{user_email}%"))
        )
    if status:
        stmt = stmt.where(AuditLogORM.status == status.upper())
    if from_date:
        stmt = stmt.where(AuditLogORM.created_at >= from_date)
    if to_date:
        # include the full to_date day
        stmt = stmt.where(AuditLogORM.created_at <= f"{to_date}T23:59:59")

    stmt = stmt.offset(offset).limit(limit)
    rows = session.execute(stmt).scalars().all()
    return [_to_out(r) for r in rows]


@router.get(
    "/logs/{resource_type}/{resource_id}",
    response_model=list[AuditLogOut],
    summary="Historique d'une ressource",
    description=(
        "Retourne toutes les actions effectuées sur une ressource spécifique "
        "(facture, actif, utilisateur, etc.). "
        "Utile pour la traçabilité complète d'un objet. "
        "Réservé aux rôles Admin et Direction."
    ),
    response_description="Historique complet trié par date décroissante",
)
def resource_history(
    resource_type: str,
    resource_id: str,
    limit: int = Query(200, ge=1, le=500),
    _: dict = _ALLOWED,
    session: Session = Depends(get_session),
):
    rows = session.execute(
        select(AuditLogORM)
        .where(
            AuditLogORM.resource_type == resource_type,
            (AuditLogORM.resource_id == resource_id) | (AuditLogORM.entity_id == resource_id),
        )
        .order_by(AuditLogORM.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return [_to_out(r) for r in rows]


@router.get(
    "/verify-integrity",
    summary="Vérifier l'intégrité des journaux d'audit",
    description=(
        "Recalcule le HMAC de chaque entrée et détecte toute altération. "
        "Réservé au rôle Admin."
    ),
)
def verify_integrity(
    _: dict = Depends(require_role("Admin")),
    session: Session = Depends(get_session),
):
    rows = session.execute(select(AuditLogORM).order_by(AuditLogORM.created_at)).scalars().all()

    valid = 0
    null_hash_entries = []
    tampered = []
    for row in rows:
        if not row.row_hash:
            # Pre-HMAC entry — backfill hash, count separately from genuine tampering
            row.row_hash = compute_row_hash(row)
            null_hash_entries.append({
                "id": str(row.id),
                "created_at": row.created_at.isoformat(),
                "action": row.action,
            })
            valid += 1
        elif verify_row_hash(row):
            valid += 1
        else:
            tampered.append({
                "id": str(row.id),
                "created_at": row.created_at.isoformat(),
                "action": row.action,
            })

    total = len(rows)
    score = (valid / total * 100) if total > 0 else 100.0

    null_count = len(null_hash_entries)
    tampered_count = len(tampered)

    if null_count and tampered_count:
        detail_msg = (
            f"{null_count} entrée(s) antérieure(s) au système HMAC (non suspectes). "
            f"{tampered_count} entrée(s) potentiellement altérée(s)."
        )
    elif null_count:
        detail_msg = (
            f"{null_count} entrée(s) antérieure(s) au système HMAC (non suspectes). "
            f"Score recalculé: {score:.1f}%."
        )
    elif tampered_count:
        detail_msg = (
            f"{tampered_count} entrée(s) potentiellement altérée(s) détectée(s). "
            f"Score: {score:.1f}%."
        )
    else:
        detail_msg = f"Intégrité vérifiée — {total} entrées conformes. Score: {score:.1f}%."

    log_action(session, AuditLogCreate(
        action="AUDIT_INTEGRITY_CHECK",
        resource_type="AuditLog",
        status="SUCCESS" if not tampered else "FAILURE",
        detail=detail_msg,
    ))
    session.commit()

    return {
        "total_checked": total,
        "valid": valid,
        "null_hash_count": null_count,
        "tampered_count": tampered_count,
        "tampered_entries": tampered,
        "integrity_score": round(score, 2),
        "message": detail_msg,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
