from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Index,
    Integer, JSON, String, Text, func,
)
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.storage.db import Base

# ─────────────────────────────────────────────────────────────────────────────
# Confidence field names that appear as two columns each (value + _conf).
# Declared here so the repository can iterate them instead of repeating code.
# ─────────────────────────────────────────────────────────────────────────────
CONFIDENCE_FIELD_NAMES = [
    "issuer_name", "issuer_tax_id",
    "recipient_name", "recipient_tax_id",
    "invoice_number", "invoice_date", "due_date",
    "amount_ht", "tva_rate", "tva_amount", "amount_ttc",
]


class InvoiceORM(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        Index("idx_invoices_status", "status"),
        Index("idx_invoices_direction_status", "direction", "status"),
        Index("idx_invoices_due_date", "due_date"),
        Index("idx_invoices_invoice_number", "invoice_number"),
        Index("idx_invoices_dup_detection", "issuer_tax_id", "invoice_number", "amount_ttc"),
    )

    # ── Identity ──────────────────────────────────────────────────────────────
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    file_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    raw_file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_mime_type: Mapped[str | None] = mapped_column(String(64))
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    extraction_method: Mapped[str | None] = mapped_column(String(32))
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)

    # ── Extracted fields + confidence scores ──────────────────────────────────
    issuer_name: Mapped[str | None] = mapped_column(Text)
    issuer_name_conf: Mapped[float | None] = mapped_column(Float)
    issuer_tax_id: Mapped[str | None] = mapped_column(Text)
    issuer_tax_id_conf: Mapped[float | None] = mapped_column(Float)
    recipient_name: Mapped[str | None] = mapped_column(Text)
    recipient_name_conf: Mapped[float | None] = mapped_column(Float)
    recipient_tax_id: Mapped[str | None] = mapped_column(Text)
    recipient_tax_id_conf: Mapped[float | None] = mapped_column(Float)
    invoice_number: Mapped[str | None] = mapped_column(Text)
    invoice_number_conf: Mapped[float | None] = mapped_column(Float)
    invoice_date: Mapped[date | None] = mapped_column(Date)
    invoice_date_conf: Mapped[float | None] = mapped_column(Float)
    due_date: Mapped[date | None] = mapped_column(Date)
    due_date_conf: Mapped[float | None] = mapped_column(Float)
    amount_ht: Mapped[float | None] = mapped_column(Float)
    amount_ht_conf: Mapped[float | None] = mapped_column(Float)
    tva_rate: Mapped[float | None] = mapped_column(Float)
    tva_rate_conf: Mapped[float | None] = mapped_column(Float)
    tva_amount: Mapped[float | None] = mapped_column(Float)
    tva_amount_conf: Mapped[float | None] = mapped_column(Float)
    amount_ttc: Mapped[float | None] = mapped_column(Float)
    amount_ttc_conf: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="TND")
    raw_extracted_json: Mapped[dict | None] = mapped_column(JSON)

    # ── Classification ────────────────────────────────────────────────────────
    cost_catalog_id: Mapped[str | None] = mapped_column(Text)
    accounting_compte: Mapped[str | None] = mapped_column(String(16))
    accounting_label: Mapped[str | None] = mapped_column(Text)
    charge_nature: Mapped[str | None] = mapped_column(String(16))
    charge_type: Mapped[str | None] = mapped_column(String(8))
    matched_po_id: Mapped[str | None] = mapped_column(Text)
    matched_contract_id: Mapped[str | None] = mapped_column(Text)
    matched_client_id: Mapped[str | None] = mapped_column(Text)
    # AI-populated fields
    payment_term_days: Mapped[int | None] = mapped_column(Integer)
    classification_reason: Mapped[str | None] = mapped_column(Text)
    classification_pass: Mapped[str | None] = mapped_column(String(32))

    # ── Human review ──────────────────────────────────────────────────────────
    human_review_required: Mapped[bool] = mapped_column(Boolean, default=False)
    human_review_notes: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Lifecycle timestamps ──────────────────────────────────────────────────
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    export_reference: Mapped[str | None] = mapped_column(Text)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now()
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    line_items: Mapped[list[LineItemORM]] = relationship(
        "LineItemORM",
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="LineItemORM.line_number",
    )
    flags: Mapped[list[ValidationFlagORM]] = relationship(
        "ValidationFlagORM",
        back_populates="invoice",
        cascade="all, delete-orphan",
    )
    history: Mapped[list[StatusHistoryORM]] = relationship(
        "StatusHistoryORM",
        back_populates="invoice",
        order_by="StatusHistoryORM.changed_at",
    )
    payments: Mapped[list[PaymentORM]] = relationship(
        "PaymentORM",
        back_populates="invoice",
    )


class LineItemORM(Base):
    __tablename__ = "line_items"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    invoice_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[float | None] = mapped_column(Float)
    unit_price: Mapped[float | None] = mapped_column(Float)
    line_total: Mapped[float | None] = mapped_column(Float)
    tva_rate: Mapped[float | None] = mapped_column(Float)

    invoice: Mapped[InvoiceORM] = relationship("InvoiceORM", back_populates="line_items")


class ValidationFlagORM(Base):
    __tablename__ = "validation_flags"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    invoice_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    flag_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    field_name: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())

    invoice: Mapped[InvoiceORM] = relationship("InvoiceORM", back_populates="flags")


class StatusHistoryORM(Base):
    __tablename__ = "status_history"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    invoice_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    changed_by: Mapped[str] = mapped_column(String(64), default="agent")
    notes: Mapped[str | None] = mapped_column(Text)

    invoice: Mapped[InvoiceORM] = relationship("InvoiceORM", back_populates="history")


class BudgetPlanORM(Base):
    """Editable annual budget plan — one row per catalog_id per year."""
    __tablename__ = "budget_plan_entries"

    catalog_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    monthly: Mapped[list] = mapped_column(JSON, nullable=False)  # 12 floats
    note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now(), onupdate=func.now())


class PaymentORM(Base):
    __tablename__ = "payments"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    invoice_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("invoices.id"), nullable=False
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_reference: Mapped[str | None] = mapped_column(Text)
    payment_method: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())

    invoice: Mapped[InvoiceORM] = relationship("InvoiceORM", back_populates="payments")
