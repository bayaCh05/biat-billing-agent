"""Audit trail service — append-only compliance log.

Usage:
    from src.services.audit_service import log_action
    from src.models.audit import AuditLogCreate

    log_action(session, AuditLogCreate(
        user_id=user.id, user_email=user.email, user_role=user.role,
        action="APPROVE", resource_type="InvoiceRecord", resource_id=invoice_id,
        ip_address=request.client.host,
    ))
    session.commit()  # caller handles the transaction

NEVER call session.commit() inside this function — it must be transactional with the
surrounding business operation so either both succeed or both fail.
"""
from __future__ import annotations

import os

from sqlalchemy.orm import Session

from src.models.audit import AuditLogCreate
from src.storage.orm_models_audit import AuditLogORM

# IPs des proxies de confiance depuis lesquels X-Forwarded-For est accepté.
# Format : liste d'IPs séparées par des virgules (ex: "10.0.0.1,10.0.0.2").
# Si vide (défaut), X-Forwarded-For est ignoré et l'IP directe est utilisée.
_TRUSTED_PROXIES: frozenset[str] = frozenset(
    ip.strip()
    for ip in os.getenv("TRUSTED_PROXY_IPS", "").split(",")
    if ip.strip()
)


def log_action(session: Session, entry: AuditLogCreate) -> None:
    """Append one audit entry to the session (does not commit)."""
    from api.security.audit_integrity import compute_row_hash

    row = AuditLogORM(
        user_id=entry.user_id,
        user_email=entry.user_email,
        actor=entry.user_email or entry.user_id or "",
        user_role=entry.user_role,
        action=entry.action,
        resource_type=entry.resource_type,
        resource_id=entry.resource_id,
        entity_id=entry.resource_id,
        before_value=entry.before_value,
        after_value=entry.after_value,
        ip_address=entry.ip_address,
        user_agent=entry.user_agent,
        status=entry.status,
        detail=entry.detail,
    )
    session.add(row)
    # Flush to let SQLAlchemy apply column defaults (id, created_at) before
    # computing the hash — without flush, row.id and row.created_at are None.
    session.flush()
    row.row_hash = compute_row_hash(row)


def _ip(request) -> str | None:
    """Extrait l'IP client — n'accepte X-Forwarded-For que depuis des proxies de confiance."""
    if request is None:
        return None
    client = getattr(request, "client", None)
    direct_ip = client.host if client else None
    # N'utiliser X-Forwarded-For que si la requête arrive d'un proxy connu
    if _TRUSTED_PROXIES and direct_ip in _TRUSTED_PROXIES:
        forwarded = (request.headers or {}).get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return direct_ip


def _ua(request) -> str | None:
    """Extract User-Agent header from a FastAPI Request."""
    if request is None:
        return None
    return (request.headers or {}).get("user-agent")
