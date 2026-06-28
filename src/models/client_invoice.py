"""Modèle de données pour les factures émises par BIAT IT (factures client)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


class ClientInvoiceStatus(str, Enum):
    DRAFT     = "draft"
    SENT      = "sent"
    PAID      = "paid"
    CANCELLED = "cancelled"


class ClientLineItem(BaseModel):
    description:      str
    quantity:         float = 1.0
    unit_price:       float
    line_total:       float          # quantity × unit_price, set by builder
    tva_rate:         float = 19.0
    tva_amount:       float          # line_total × tva_rate / 100, set by builder
    compte_produit:   str = "7061"   # compte de produit (classe 7)
    # Project billing metadata (None for non-project lines)
    charte_reference: str | None = None
    phase_id:         str | None = None


class ClientInvoice(BaseModel):
    id:             UUID = Field(default_factory=uuid4)
    invoice_number: str

    # Dates
    invoice_date: date
    due_date:     date

    # Issuer (always BIAT IT — populated from config)
    issuer_name:    str
    issuer_tax_id:  str
    issuer_address: str = ""

    # Client
    client_id:      str
    client_name:    str
    client_tax_id:  str
    client_address: str = ""

    # Lines and amounts
    line_items:  list[ClientLineItem] = Field(default_factory=list)
    amount_ht:   float = 0.0
    tva_amount:  float = 0.0
    amount_ttc:  float = 0.0

    # Metadata
    status:             ClientInvoiceStatus = ClientInvoiceStatus.DRAFT
    source_template_id: str | None = None
    notes:              str | None = None
    pdf_path:           str | None = None

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sent_at:    datetime | None = None
    paid_at:    datetime | None = None

    # ── BCT export compliance (Banque Centrale de Tunisie — Circulaire 2025-13) ─
    currency:                str   = "TND"   # TND | EUR | USD | GBP
    is_export:               bool  = False
    domiciliation_bank:      str | None   = None
    domiciliation_number:    str | None   = None
    shipment_date:           date | None  = None
    repatriation_deadline:   date | None  = None   # auto = shipment_date + 120 j
    repatriation_date:       date | None  = None
    payment_guarantee_type:  str | None   = None   # STANDARD | CREDOC_IRREVOCABLE | BCT_AUTHORIZATION
    foreign_currency_amount: float | None = None
    exchange_rate:           float | None = None   # rate at payment date

    @model_validator(mode="after")
    def _compute_totals(self) -> "ClientInvoice":
        if self.line_items:
            self.amount_ht  = round(sum(li.line_total  for li in self.line_items), 3)
            self.tva_amount = round(sum(li.tva_amount  for li in self.line_items), 3)
            self.amount_ttc = round(self.amount_ht + self.tva_amount, 3)
        # Auto-compute BCT repatriation deadline (120 days from shipment)
        if self.is_export and self.shipment_date and self.repatriation_deadline is None:
            from datetime import timedelta
            self.repatriation_deadline = self.shipment_date + timedelta(days=120)
        return self
