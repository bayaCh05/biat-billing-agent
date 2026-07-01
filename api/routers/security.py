"""Security dashboard endpoints — Admin only."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.auth import require_role
from api.deps import get_session
from src.storage.orm_models_audit import AuditLogORM
from src.storage.orm_models_users import UserORM

router = APIRouter(prefix="/security", tags=["admin"])

_ADMIN = Depends(require_role("Admin"))


@router.get(
    "/summary",
    summary="Tableau de bord sécurité",
    description="Résumé de l'état de sécurité — logins, comptes verrouillés, intégrité audit. Admin only.",
)
def security_summary(
    _: dict = _ADMIN,
    session: Session = Depends(get_session),
):
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # Auth stats from audit log
    total_logins_today = session.scalar(
        select(func.count()).select_from(AuditLogORM).where(
            AuditLogORM.action == "LOGIN_SUCCESS",
            AuditLogORM.created_at >= today_start,
        )
    ) or 0

    failed_logins_today = session.scalar(
        select(func.count()).select_from(AuditLogORM).where(
            AuditLogORM.action == "LOGIN_FAILURE",
            AuditLogORM.created_at >= today_start,
        )
    ) or 0

    unauthorized_today = session.scalar(
        select(func.count()).select_from(AuditLogORM).where(
            AuditLogORM.action == "UNAUTHORIZED_ACCESS",
            AuditLogORM.created_at >= today_start,
        )
    ) or 0

    uploads_today = session.scalar(
        select(func.count()).select_from(AuditLogORM).where(
            AuditLogORM.action.in_(["FILE_UPLOADED", "INVOICE_UPLOADED"]),
            AuditLogORM.created_at >= today_start,
        )
    ) or 0

    rejected_files_today = session.scalar(
        select(func.count()).select_from(AuditLogORM).where(
            AuditLogORM.action == "FILE_REJECTED",
            AuditLogORM.created_at >= today_start,
        )
    ) or 0

    # Locked accounts
    now = datetime.now(timezone.utc)
    locked_users = session.execute(
        select(UserORM).where(
            UserORM.locked_until > now,
            UserORM.is_active == True,  # noqa: E712
        )
    ).scalars().all()

    # Accounts with recent failures (last 24h)
    suspicious = session.execute(
        select(UserORM).where(
            UserORM.failed_login_attempts > 0,
            UserORM.last_failed_login >= now - timedelta(hours=24),
        ).order_by(UserORM.failed_login_attempts.desc()).limit(10)
    ).scalars().all()

    # Last integrity check from audit log
    last_check = session.execute(
        select(AuditLogORM).where(
            AuditLogORM.action == "AUDIT_INTEGRITY_CHECK",
        ).order_by(AuditLogORM.created_at.desc()).limit(1)
    ).scalar_one_or_none()

    last_integrity_score: float | None = None
    last_integrity_check: str | None = None
    if last_check:
        last_integrity_check = last_check.created_at.isoformat()
        detail = last_check.detail or ""
        try:
            # Extract score from "Score: XX.X%, ..."
            score_part = detail.split("Score:")[1].split("%")[0].strip()
            last_integrity_score = float(score_part)
        except Exception:
            pass

    # Active sessions count
    active_sessions = 0
    try:
        from src.storage.orm_models_auth import ActiveTokenORM
        active_sessions = session.scalar(
            select(func.count()).select_from(ActiveTokenORM).where(
                ActiveTokenORM.revoked == False,  # noqa: E712
                ActiveTokenORM.expires_at > now,
            )
        ) or 0
    except Exception:
        pass

    return {
        "total_logins_today": total_logins_today,
        "failed_logins_today": failed_logins_today,
        "locked_accounts_count": len(locked_users),
        "uploads_today": uploads_today,
        "rejected_files_today": rejected_files_today,
        "last_integrity_check": last_integrity_check,
        "last_integrity_score": last_integrity_score,
        "tampered_entries_count": 0,
        "active_sessions_count": active_sessions,
        "unauthorized_access_attempts_today": unauthorized_today,
        "accounts_with_recent_failures": [
            {
                "email": u.email,
                "failed_attempts": u.failed_login_attempts,
                "last_attempt": u.last_failed_login.isoformat() if u.last_failed_login else None,
            }
            for u in suspicious
        ],
        "locked_accounts": [
            {
                "id": str(u.id),
                "email": u.email,
                "locked_until": u.locked_until.isoformat() if u.locked_until else None,
                "failed_attempts": u.failed_login_attempts,
            }
            for u in locked_users
        ],
    }


@router.post(
    "/unlock-account/{user_id}",
    summary="Déverrouiller un compte",
    description="Déverrouille manuellement un compte verrouillé. Admin only.",
)
def unlock_account(
    user_id: str,
    _: dict = _ADMIN,
    session: Session = Depends(get_session),
):
    from uuid import UUID
    from src.models.audit import AuditLogCreate
    from src.services.audit_service import log_action

    try:
        uid = UUID(user_id)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(400, "UUID invalide.")

    user = session.get(UserORM, uid)
    if not user:
        from fastapi import HTTPException
        raise HTTPException(404, "Utilisateur non trouvé.")

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_failed_login = None
    log_action(session, AuditLogCreate(
        user_id=user_id, user_email=user.email,
        action="ACCOUNT_UNLOCKED", resource_type="User", resource_id=user_id,
        status="SUCCESS", detail="Compte déverrouillé manuellement par Admin",
    ))
    session.commit()
    return {"message": f"Compte {user.email} déverrouillé."}
