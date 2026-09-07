"""AuditLog ORM — BCT-compliant audit trail for all sensitive operations."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from src.storage.db import Base


class AuditLogORM(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_logs_resource_type", "resource_type"),
        Index("idx_audit_logs_resource_id",   "resource_id"),
        Index("idx_audit_logs_user_id",        "user_id"),
    )

    # ── Identity & timestamp ──────────────────────────────────────────────────
    id:         Mapped[UUID]     = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
        default=lambda: datetime.now(timezone.utc),
    )

    # ── Who ───────────────────────────────────────────────────────────────────
    user_id:    Mapped[str | None] = mapped_column(String(64),  nullable=True)
    user_email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_role:  Mapped[str | None] = mapped_column(String(32),  nullable=True)

    # ── Backwards-compat alias (actor = user_email for old seed data) ─────────
    actor:      Mapped[str]        = mapped_column(String(128), nullable=False, default="")

    # ── What ──────────────────────────────────────────────────────────────────
    action:        Mapped[str]         = mapped_column(String(64),  nullable=False, index=True)
    resource_type: Mapped[str | None]  = mapped_column(String(64),  nullable=True)
    resource_id:   Mapped[str | None]  = mapped_column(String(64),  nullable=True)

    # ── Backwards-compat alias (entity_id = resource_id for old seed data) ───
    entity_id:  Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ── State snapshot ────────────────────────────────────────────────────────
    before_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_value:  Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # ── Request context ───────────────────────────────────────────────────────
    ip_address: Mapped[str | None] = mapped_column(String(64),  nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # ── Result ────────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="SUCCESS")

    # ── Human-readable note ───────────────────────────────────────────────────
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Tamper detection ──────────────────────────────────────────────────────
    row_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ── HMAC rebaseline (post-2026-07-10 secret rotation, never overwrites
    # row_hash — see docs/audit_hmac_incident.md and scripts/rebaseline_audit_hmac.py) ──
    rebaseline_hash:   Mapped[str | None] = mapped_column(String(64),  nullable=True)
    rebaselined_at:    Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rebaseline_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── HMAC rebaseline, generation 2 (post-2026-09-07 AUDIT_HMAC_SECRET
    # introduction — see docs/audit_hmac_incident.md section 8). Archives
    # the generation-1 values above before they get overwritten under the
    # new secret, so the 2026-07-15 rebaseline record is never lost. ──
    prior_rebaseline_hash:   Mapped[str | None] = mapped_column(String(64),  nullable=True)
    prior_rebaselined_at:    Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    prior_rebaseline_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
