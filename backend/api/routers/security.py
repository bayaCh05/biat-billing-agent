"""Security dashboard endpoints — Admin only."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth import require_role
from api.deps import get_session
from api.routers.audit import compute_integrity_summary

router = APIRouter(prefix="/security", tags=["admin"])

_log = logging.getLogger(__name__)

_ADMIN = Depends(require_role("Admin"))


@router.get(
    "/summary",
    summary="Tableau de bord sécurité",
    description="Résumé de l'état de sécurité — logins, comptes verrouillés, intégrité audit. Admin only.",
)
async def security_summary(
    _: dict = _ADMIN,
    session: Session = Depends(get_session),
):
    from src.storage.documents.service_bridge import security_summary_mongo

    # Live-computed, merged SQLite + Mongo tampered-entry count (see
    # compute_integrity_summary) — never hardcoded, so known tamper/backfill
    # findings (e.g. legacy SQLite HMAC-key-rotation mismatches) stay visible
    # to Admins here rather than being silently reported as zero.
    integrity = await compute_integrity_summary(session)

    mongo_result = await security_summary_mongo()
    if mongo_result is None:
        # Login/lockout stats are written Mongo-only (see CLAUDE.md) — the
        # old SQLite fallback here could only ever serve permanently stale
        # data. `integrity` above is unaffected — it's a genuine dual-source
        # merge (SQLite HMAC chain + Mongo), not a fallback.
        _log.warning("security_summary: MongoDB indisponible — retour de statistiques vides.")
        return {
            "total_logins_today": 0,
            "failed_logins_today": 0,
            "locked_accounts_count": 0,
            "uploads_today": 0,
            "rejected_files_today": 0,
            "last_integrity_check": None,
            "last_integrity_score": None,
            "tampered_entries_count": integrity["tampered_count"],
            "active_sessions_count": 0,
            "unauthorized_access_attempts_today": 0,
            "accounts_with_recent_failures": [],
            "locked_accounts": [],
        }

    mongo_result["tampered_entries_count"] = integrity["tampered_count"]
    return mongo_result


@router.post(
    "/unlock-account/{user_id}",
    summary="Déverrouiller un compte",
    description="Déverrouille manuellement un compte verrouillé. Admin only.",
)
async def unlock_account(
    user_id: str,
    _: dict = _ADMIN,
):
    from uuid import UUID
    from fastapi import HTTPException
    from src.models.audit import AuditLogCreate
    from src.storage.documents.service_bridge import log_audit_event_native, unlock_account_native

    try:
        UUID(user_id)
    except ValueError:
        raise HTTPException(400, "UUID invalide.")

    user = await unlock_account_native(user_id)
    if not user:
        raise HTTPException(404, "Utilisateur non trouvé.")

    await log_audit_event_native(AuditLogCreate(
        user_id=user_id, user_email=user.email,
        action="ACCOUNT_UNLOCKED", resource_type="User", resource_id=user_id,
        status="SUCCESS", detail="Compte déverrouillé manuellement par Admin",
    ))
    return {"message": f"Compte {user.email} déverrouillé."}
