from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Generic, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from src.models.enums import (
    ChargeNature,
    ChargeType,
    ExtractionMethod,
    FlagSeverity,
    FlagType,
    InvoiceDirection,
    InvoiceStatus,
)

T = TypeVar("T")


class ConfidenceField(BaseModel, Generic[T]):
    """A field value paired with a confidence score and the source text snippet."""

    value: T | None = None
    confidence: float = 0.0
    source: str | None = None  # substring of original text the value was drawn from


class LineItem(BaseModel):
    line_number: int
    description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    line_total: float | None = None
    tva_rate: float | None = None


class ValidationFlag(BaseModel):
    flag_type: FlagType
    severity: FlagSeverity
    field_name: str | None = None
    message: str
    resolved: bool = False
    resolved_at: datetime | None = None
    resolved_by: str | None = None


class InvoiceRecord(BaseModel):
    # ── Identity ───────────────────────────────────────────────────────────────
    id: UUID = Field(default_factory=uuid4)
    file_hash: str
    raw_file_path: str
    file_mime_type: str | None = None
    direction: InvoiceDirection = InvoiceDirection.UNKNOWN
    status: InvoiceStatus = InvoiceStatus.RECEIVED
    extraction_method: ExtractionMethod | None = None
    retry_count: int = 0
    last_error: str | None = None

    # ── Extracted fields ───────────────────────────────────────────────────────
    issuer_name: ConfidenceField[str] = Field(default_factory=ConfidenceField)
    issuer_tax_id: ConfidenceField[str] = Field(default_factory=ConfidenceField)
    recipient_name: ConfidenceField[str] = Field(default_factory=ConfidenceField)
    recipient_tax_id: ConfidenceField[str] = Field(default_factory=ConfidenceField)
    invoice_number: ConfidenceField[str] = Field(default_factory=ConfidenceField)
    invoice_date: ConfidenceField[date] = Field(default_factory=ConfidenceField)
    due_date: ConfidenceField[date] = Field(default_factory=ConfidenceField)
    amount_ht: ConfidenceField[float] = Field(default_factory=ConfidenceField)
    tva_rate: ConfidenceField[float] = Field(default_factory=ConfidenceField)
    tva_amount: ConfidenceField[float] = Field(default_factory=ConfidenceField)
    amount_ttc: ConfidenceField[float] = Field(default_factory=ConfidenceField)
    currency: str = "TND"
    line_items: list[LineItem] = Field(default_factory=list)
    raw_extracted_json: dict | None = None  # full LLM response, for debugging
    raw_extracted_text: str = ""            # original OCR/PDF text fed to the LLM

    # ── Classification ─────────────────────────────────────────────────────────
    cost_catalog_id: str | None = None       # identifiant dans cost_catalog.yaml
    accounting_compte: str | None = None     # numéro de compte (ex. "6112")
    accounting_label: str | None = None      # libellé comptable
    charge_nature: ChargeNature | None = None
    charge_type: ChargeType | None = None
    matched_po_id: str | None = None
    matched_contract_id: str | None = None
    matched_client_id: str | None = None

    # ── AI classification metadata ─────────────────────────────────────────────
    payment_term_days: int | None = None
    classification_reason: str | None = None
    classification_pass: str | None = None

    # ── Validation ─────────────────────────────────────────────────────────────
    flags: list[ValidationFlag] = Field(default_factory=list)
    human_review_required: bool = False
    human_review_notes: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None

    # ── Lifecycle timestamps ───────────────────────────────────────────────────
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    extracted_at: datetime | None = None
    classified_at: datetime | None = None
    validated_at: datetime | None = None
    exported_at: datetime | None = None
    export_reference: str | None = None
    paid_at: datetime | None = None        # supplier invoices
    collected_at: datetime | None = None   # client invoices
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def has_errors(self) -> bool:
        return any(f.severity == FlagSeverity.ERROR and not f.resolved for f in self.flags)

    @property
    def has_warnings(self) -> bool:
        return any(f.severity == FlagSeverity.WARNING and not f.resolved for f in self.flags)

    def add_flag(self, flag: ValidationFlag) -> None:
        self.flags.append(flag)
        if flag.severity == FlagSeverity.ERROR:
            self.human_review_required = True

    model_config = {"arbitrary_types_allowed": True}
