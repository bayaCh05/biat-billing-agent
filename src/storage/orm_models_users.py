"""SQLAlchemy ORM for user accounts (admin-managed)."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column

from src.storage.db import Base


class UserORM(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    nom: Mapped[str] = mapped_column(String(64), nullable=False)
    prenom: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)          # COMPTABLE | CHEF_PROJET | DIRECTION | ADMIN
    departement: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    is_first_login: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
