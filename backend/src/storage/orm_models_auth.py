"""ORM models for token revocation and active session tracking."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.storage.db import Base


class RevokedTokenORM(Base):
    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    reason: Mapped[str] = mapped_column(String(32), nullable=False, default="logout")
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class ActiveTokenORM(Base):
    __tablename__ = "active_tokens"
    __table_args__ = (
        Index("idx_active_tokens_user_id", "user_id"),
    )

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(100), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
