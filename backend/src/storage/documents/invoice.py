"""Document Beanie pour les factures — migration de InvoiceORM + tables enfants.

Décisions Phase 0 (confirmées) :
  - line_items, flags, history : embarqués dans le document (cascade naturelle,
    accès toujours conjoints, suppression atomique).
  - id : UUID CRITIQUE — ChromaDB utilise str(invoice.id) comme clé primaire
    dans la collection invoice_embeddings. Ne jamais changer en ObjectId.
  - file_hash : index unique (détection de doublons au niveau fichier).
  - Indexes composés reproduits depuis __table_args__ de InvoiceORM.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from beanie import Document, Indexed
from pydantic import BaseModel, Field
from pymongo import ASCENDING, IndexModel


# ── Sous-documents embarqués ──────────────────────────────────────────────────

class LineItemEmbed(BaseModel):
    """Ligne de facturation — correspond à LineItemORM (table line_items)."""
    id: UUID = Field(default_factory=uuid4)
    line_number: int
    description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    line_total: float | None = None
    tva_rate: float | None = None


class ValidationFlagEmbed(BaseModel):
    """Anomalie de validation — correspond à ValidationFlagORM (table validation_flags)."""
    id: UUID = Field(default_factory=uuid4)
    flag_type: str
    severity: str
    field_name: str | None = None
    message: str
    resolved: bool = False
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StatusHistoryEmbed(BaseModel):
    """Transition de statut — correspond à StatusHistoryORM (table status_history)."""
    id: UUID = Field(default_factory=uuid4)
    from_status: str | None = None
    to_status: str
    changed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    changed_by: str = "agent"
    notes: str | None = None


# ── Document principal ────────────────────────────────────────────────────────

class InvoiceDocument(Document):
    """Facture fournisseur ou client.

    Correspond à InvoiceORM (table invoices) + line_items + validation_flags
    + status_history (tous embarqués).

    ⚠️  id UUID — NE PAS changer en ObjectId :
        ChromaDB stocke str(invoice.id) comme clé dans invoice_embeddings.
        Tout changement de type rendrait les embeddings existants inaccessibles.
    """

    id: UUID = Field(default_factory=uuid4)

    # ── Identité fichier ──────────────────────────────────────────────────────
    file_hash: Annotated[str, Indexed(unique=True)]
    raw_file_path: str
    file_mime_type: str | None = None
    direction: str
    status: Annotated[str, Indexed()]
    extraction_method: str | None = None
    retry_count: int = 0
    last_error: str | None = None

    # ── Champs extraits + scores de confiance (11 paires) ────────────────────
    issuer_name: str | None = None
    issuer_name_conf: float | None = None
    issuer_tax_id: str | None = None
    issuer_tax_id_conf: float | None = None
    recipient_name: str | None = None
    recipient_name_conf: float | None = None
    recipient_tax_id: str | None = None
    recipient_tax_id_conf: float | None = None
    invoice_number: str | None = None
    invoice_number_conf: float | None = None
    invoice_date: date | None = None
    invoice_date_conf: float | None = None
    due_date: date | None = None
    due_date_conf: float | None = None
    amount_ht: float | None = None
    amount_ht_conf: float | None = None
    tva_rate: float | None = None
    tva_rate_conf: float | None = None
    tva_amount: float | None = None
    tva_amount_conf: float | None = None
    amount_ttc: float | None = None
    amount_ttc_conf: float | None = None
    currency: str = "TND"
    raw_extracted_json: dict[str, Any] | None = None

    # ── Classification ────────────────────────────────────────────────────────
    cost_catalog_id: str | None = None
    accounting_compte: str | None = None
    accounting_label: str | None = None
    charge_nature: str | None = None
    charge_type: str | None = None
    matched_po_id: str | None = None
    matched_contract_id: str | None = None
    matched_client_id: str | None = None
    payment_term_days: int | None = None
    classification_reason: str | None = None
    classification_pass: str | None = None

    # ── Révision humaine ──────────────────────────────────────────────────────
    human_review_required: bool = False
    human_review_notes: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None

    # ── Horodatages cycle de vie ──────────────────────────────────────────────
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    extracted_at: datetime | None = None
    classified_at: datetime | None = None
    validated_at: datetime | None = None
    exported_at: datetime | None = None
    export_reference: str | None = None
    paid_at: datetime | None = None
    collected_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # ── Sous-documents embarqués ──────────────────────────────────────────────
    line_items: list[LineItemEmbed] = Field(default_factory=list)
    flags: list[ValidationFlagEmbed] = Field(default_factory=list)
    history: list[StatusHistoryEmbed] = Field(default_factory=list)

    class Settings:
        name = "invoices"
        indexes = [
            IndexModel([("direction", ASCENDING), ("status", ASCENDING)]),
            IndexModel([("due_date", ASCENDING)]),
            IndexModel([("invoice_number", ASCENDING)]),
            IndexModel([
                ("issuer_tax_id", ASCENDING),
                ("invoice_number", ASCENDING),
                ("amount_ttc", ASCENDING),
            ]),
        ]
