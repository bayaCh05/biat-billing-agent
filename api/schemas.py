"""Response/request schemas for the FastAPI layer."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from src.models.invoice import InvoiceRecord


# ── Invoice ───────────────────────────────────────────────────────────────────

class ConfidenceFieldOut(BaseModel):
    value: Any = None
    confidence: float = 0.0


class LineItemOut(BaseModel):
    line_number: int
    description: str | None
    quantity: float | None
    unit_price: float | None
    line_total: float | None
    tva_rate: float | None


class FlagOut(BaseModel):
    flag_type: str
    severity: str
    field_name: str | None
    message: str
    resolved: bool


class InvoiceOut(BaseModel):
    id: str
    status: str
    direction: str
    issuer_name: ConfidenceFieldOut
    issuer_tax_id: ConfidenceFieldOut
    recipient_name: ConfidenceFieldOut
    invoice_number: ConfidenceFieldOut
    invoice_date: ConfidenceFieldOut
    amount_ht: ConfidenceFieldOut
    tva_rate: ConfidenceFieldOut
    tva_amount: ConfidenceFieldOut
    amount_ttc: ConfidenceFieldOut
    currency: str
    accounting_compte: str | None
    accounting_label: str | None
    extraction_method: str | None
    flags: list[FlagOut]
    human_review_required: bool
    received_at: datetime
    line_items: list[LineItemOut]
    # AI classification metadata
    classification_reason: str | None = None
    classification_pass: str | None = None
    payment_term_days: int | None = None

    @classmethod
    def from_record(cls, inv: InvoiceRecord) -> "InvoiceOut":
        def cf(field):
            return ConfidenceFieldOut(value=field.value, confidence=field.confidence)

        return cls(
            id=str(inv.id),
            status=inv.status.value,
            direction=inv.direction.value,
            issuer_name=cf(inv.issuer_name),
            issuer_tax_id=cf(inv.issuer_tax_id),
            recipient_name=cf(inv.recipient_name),
            invoice_number=cf(inv.invoice_number),
            invoice_date=ConfidenceFieldOut(
                value=inv.invoice_date.value.isoformat() if inv.invoice_date.value else None,
                confidence=inv.invoice_date.confidence,
            ),
            amount_ht=cf(inv.amount_ht),
            tva_rate=cf(inv.tva_rate),
            tva_amount=cf(inv.tva_amount),
            amount_ttc=cf(inv.amount_ttc),
            currency=inv.currency,
            accounting_compte=inv.accounting_compte,
            accounting_label=inv.accounting_label,
            extraction_method=inv.extraction_method.value if inv.extraction_method else None,
            flags=[
                FlagOut(
                    flag_type=f.flag_type.value,
                    severity=f.severity.value,
                    field_name=f.field_name,
                    message=f.message,
                    resolved=f.resolved,
                )
                for f in inv.flags
            ],
            human_review_required=inv.human_review_required,
            received_at=inv.received_at,
            line_items=[
                LineItemOut(
                    line_number=li.line_number,
                    description=li.description,
                    quantity=li.quantity,
                    unit_price=li.unit_price,
                    line_total=li.line_total,
                    tva_rate=li.tva_rate,
                )
                for li in inv.line_items
            ],
            classification_reason=getattr(inv, "classification_reason", None),
            classification_pass=getattr(inv, "classification_pass", None),
            payment_term_days=getattr(inv, "payment_term_days", None),
        )


class InvoiceSummary(BaseModel):
    id: str
    status: str
    direction: str
    issuer_name: str | None
    invoice_number: str | None
    invoice_date: str | None
    amount_ht: float | None
    tva_rate: float | None
    tva_amount: float | None
    amount_ttc: float | None
    currency: str
    accounting_compte: str | None
    accounting_label: str | None
    extraction_method: str | None
    flags: list[FlagOut]
    human_review_required: bool
    has_errors: bool
    received_at: datetime
    classification_reason: str | None = None
    classification_pass: str | None = None
    payment_term_days: int | None = None

    @classmethod
    def from_record(cls, inv: InvoiceRecord) -> "InvoiceSummary":
        return cls(
            id=str(inv.id),
            status=inv.status.value,
            direction=inv.direction.value,
            issuer_name=inv.issuer_name.value,
            invoice_number=inv.invoice_number.value,
            invoice_date=inv.invoice_date.value.isoformat() if inv.invoice_date.value else None,
            amount_ht=inv.amount_ht.value,
            tva_rate=inv.tva_rate.value,
            tva_amount=inv.tva_amount.value,
            amount_ttc=inv.amount_ttc.value,
            currency=inv.currency,
            accounting_compte=inv.accounting_compte,
            accounting_label=inv.accounting_label,
            extraction_method=inv.extraction_method.value if inv.extraction_method else None,
            flags=[
                FlagOut(
                    flag_type=f.flag_type.value,
                    severity=f.severity.value,
                    field_name=f.field_name,
                    message=f.message,
                    resolved=f.resolved,
                )
                for f in inv.flags
            ],
            human_review_required=inv.human_review_required,
            has_errors=inv.has_errors,
            received_at=inv.received_at,
            classification_reason=getattr(inv, "classification_reason", None),
            classification_pass=getattr(inv, "classification_pass", None),
            payment_term_days=getattr(inv, "payment_term_days", None),
        )


# ── Review ────────────────────────────────────────────────────────────────────

class ReviewActionRequest(BaseModel):
    notes: str = ""


# ── Journal ───────────────────────────────────────────────────────────────────

class JournalLineOut(BaseModel):
    compte: str
    libelle: str
    debit: float = 0.0
    credit: float = 0.0


class JournalEntryOut(BaseModel):
    id: str
    reference: str
    date_ecriture: date
    description: str
    lines: list[JournalLineOut]
    source_invoice_id: str | None
    accounting_explanation: str | None = None


# ── Budget ────────────────────────────────────────────────────────────────────

class BudgetLineOut(BaseModel):
    catalog_id: str
    label: str
    budget_ytd: float
    actual_ytd: float
    variance: float
    variance_pct: float
    is_over: bool


class BudgetSummaryOut(BaseModel):
    year: int
    through_month: int
    total_budget_ytd: float
    total_actual_ytd: float
    variance_pct: float
    lines_over_budget: int
    lines: list[BudgetLineOut]


# ── Budget plan (editable) ────────────────────────────────────────────────────

class BudgetPlanEntryOut(BaseModel):
    catalog_id: str
    year: int
    label: str
    monthly: list[float]          # 12 values, index 0 = January
    note: str | None = None
    annual_total: float


class BudgetPlanEntryIn(BaseModel):
    catalog_id: str
    label: str
    monthly: list[float]          # must have exactly 12 values
    note: str | None = None


class BudgetPlanUpdateIn(BaseModel):
    label: str | None = None
    monthly: list[float] | None = None   # must have exactly 12 values if provided
    note: str | None = None


# ── CAPEX ─────────────────────────────────────────────────────────────────────

class AssetOut(BaseModel):
    id: str
    designation: str
    compte_immobilisation: str
    compte_amortissement: str | None = None
    acquisition_date: date
    acquisition_cost_ht: float
    useful_life_years: int
    depreciation_method: str
    fully_depreciated: bool


class AssetCreateRequest(BaseModel):
    designation: str
    compte_immobilisation: str
    compte_amortissement: str
    acquisition_date: date
    acquisition_cost_ht: float
    useful_life_years: int
    depreciation_method: str = "linear"


# ── KPI ───────────────────────────────────────────────────────────────────────

class KpiOut(BaseModel):
    total_invoices: int
    total_amount_ttc: float
    auto_approved: int
    auto_approval_rate: float
    flagged: int
    pending_review: int
    by_status: dict[str, int]
    # Montants agrégés pour les cartes de risque du dashboard
    exposed_amount_ttc: float = 0.0
    blocked_amount_ttc: float = 0.0


# ── Billing ───────────────────────────────────────────────────────────────────

class ClientTemplateOut(BaseModel):
    id: str
    client_code: str
    client_name: str
    service_description: str
    unit_price_ht: float
    tva_rate: float


class GenerateInvoiceRequest(BaseModel):
    template_id: str
    year: int
    month: int


class GeneratedInvoiceOut(BaseModel):
    invoice_number: str
    client_name: str
    amount_ht: float
    tva_amount: float
    amount_ttc: float
    status: str


class ClientInvoiceOut(BaseModel):
    invoice_number: str
    client_name: str
    invoice_date: str
    due_date: str
    amount_ht: float
    tva_amount: float
    amount_ttc: float
    status: str
    sent_at: str | None
    paid_at: str | None


class ActionResultOut(BaseModel):
    id: str
    action: str
    new_status: str


# ── Projects ─────────────────────────────────────────────────────────────────

class ProjectOut(BaseModel):
    id: str
    name: str
    client: str
    budget_jh: float
    consumed_jh: float
    taux_jh: float
    status: str
    start_date: str
    end_date: str | None
    budget_tnd: float
    spent_tnd: float


class ProjectPhaseOut(BaseModel):
    id: str
    project_id: str
    name: str
    planned_jh: float
    consumed_jh: float
    status: str


# ── NL Query ─────────────────────────────────────────────────────────────────

class NLQueryRequest(BaseModel):
    question: str


class NLQueryResult(BaseModel):
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    answer: str | None = None
    explanation: str | None = None
    error: str | None = None
