"""ORM for payment installments with penalty tracking."""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, Float, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from src.storage.db import Base


class PaymentInstallmentORM(Base):
    __tablename__ = "payment_installments"
    __table_args__ = (
        Index("idx_installments_invoice", "invoice_id"),
        Index("idx_installments_status", "status"),
        Index("idx_installments_due_date", "due_date"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    invoice_id: Mapped[str] = mapped_column(Text, nullable=False)
    installment_number: Mapped[int] = mapped_column(Integer, nullable=False)
    total_installments: Mapped[int] = mapped_column(Integer, nullable=False)
    base_amount: Mapped[float] = mapped_column(Float, nullable=False)
    current_amount: Mapped[float] = mapped_column(Float, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    paid_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    late_periods: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ClassificationFeedbackORM(Base):
    __tablename__ = "classification_feedback"
    __table_args__ = (
        Index("idx_feedback_invoice", "invoice_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    invoice_id: Mapped[str] = mapped_column(Text, nullable=False)
    original_compte: Mapped[str] = mapped_column(String(16), nullable=False)
    corrected_compte: Mapped[str] = mapped_column(String(16), nullable=False)
    original_catalog_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_catalog_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    corrected_by: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    corrected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
