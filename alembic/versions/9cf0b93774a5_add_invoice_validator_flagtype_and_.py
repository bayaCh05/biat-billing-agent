"""add invoice validator flagtype and budget tracker fixes

Revision ID: 9cf0b93774a5
Revises: ece2bf29445f
Create Date: 2026-06-16 15:42:38.771298

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9cf0b93774a5'
down_revision: Union[str, Sequence[str], None] = 'ece2bf29445f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Document-only migration — no DDL changes.

    Changes since initial schema (all already reflected in the DB):

    src/models/enums.py
      - FlagType.NOT_AN_INVOICE = "NOT_AN_INVOICE" added
        (stored in validation_flags.flag_type VARCHAR(64) — fits existing column)

    src/extraction/invoice_validator.py  [NEW MODULE]
      - InvoiceValidator raises NotAnInvoiceError before OCR/LLM
      - Rejects non-invoice files early; sets invoice.status = ERROR
        and adds a NOT_AN_INVOICE flag row

    src/budget/budget_tracker.py
      - BudgetTracker.ACTUAL_STATUSES: added "JOURNALED"
      - _actuals_by_catalog query: direction filter fixed from
        "fournisseur" → "SUPPLIER" (matches InvoiceDirection.SUPPLIER.value)

    src/budget/cost_analyzer.py
      - CostAnalyzer.ACTUAL_STATUSES: added "JOURNALED"
      - All direction filters: "fournisseur" → "SUPPLIER"

    src/extraction/ocr_engine.py
      - Bilingual OCR: separate fra/ara passes to eliminate bidi injection
      - _strip_bidi() removes Unicode direction control characters

    src/extraction/ocr_preprocessor.py
      - _upscale(): screenshots < 1800 px wide are upscaled before OCR
      - _enhance_contrast(): CLAHE applied between denoise and binarize
    """


def downgrade() -> None:
    """No DDL to reverse."""
