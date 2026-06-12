"""Modèles d'écritures comptables (journal général).

Une JournalEntry représente une écriture équilibrée :
  - au moins deux JournalLine
  - sum(débits) == sum(crédits) à la tolérance de 0,005 TND près

Chaque JournalLine ne peut avoir qu'un seul côté renseigné (débit OU crédit).
Une entrée non équilibrée ne peut pas être instanciée.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

_BALANCE_TOLERANCE = 0.005  # TND — tolérance d'arrondi


class JournalLine(BaseModel):
    compte: str
    libelle: str
    debit: float | None = None
    credit: float | None = None

    @model_validator(mode="after")
    def _exactly_one_side(self) -> "JournalLine":
        has_debit = self.debit is not None
        has_credit = self.credit is not None
        if has_debit == has_credit:  # both or neither
            raise ValueError(
                "Chaque ligne doit avoir exactement un montant : débit OU crédit. "
                f"Reçu : débit={self.debit}, crédit={self.credit}"
            )
        return self


class JournalEntry(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    reference: str                          # numéro de pièce (facture ou autre)
    date_ecriture: date
    description: str
    lines: list[JournalLine] = Field(min_length=2)
    source_invoice_id: UUID | None = None   # facture ayant généré l'écriture
    source_asset_id: UUID | None = None     # immobilisation (dotation amortissement)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # ── Propriétés calculées ──────────────────────────────────────────────────

    @property
    def total_debit(self) -> float:
        return round(sum(l.debit for l in self.lines if l.debit is not None), 3)

    @property
    def total_credit(self) -> float:
        return round(sum(l.credit for l in self.lines if l.credit is not None), 3)

    @property
    def is_balanced(self) -> bool:
        return abs(self.total_debit - self.total_credit) < _BALANCE_TOLERANCE

    # ── Validation ────────────────────────────────────────────────────────────

    @model_validator(mode="after")
    def _must_balance(self) -> "JournalEntry":
        if not self.is_balanced:
            raise ValueError(
                f"Écriture '{self.reference}' non équilibrée : "
                f"débit={self.total_debit:.3f} TND, crédit={self.total_credit:.3f} TND"
            )
        return self
