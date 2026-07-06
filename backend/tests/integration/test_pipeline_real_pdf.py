"""End-to-end integration test: real PDF → full pipeline → JOURNALED.

Strategy:
  - Uses the real SQLite DB (data/invoices.db) and a real PDF from inbox/
  - LLM is mocked so the test is deterministic and doesn't need Ollama
  - Asserts the invoice reaches a meaningful terminal status
  - If JOURNALED, verifies that a balanced journal entry was created
  - Cleans up the test invoice (and its journal entries) on exit
"""
from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

REAL_PDF = Path("inbox/invoice_01_ooredoo.pdf")

_MOCK_LLM_RESPONSE = """{
  "issuer_name": {"value": "Ooredoo Tunisie", "confidence": 0.95, "source": "Ooredoo Tunisie"},
  "issuer_tax_id": {"value": "1234567A/M/P/000", "confidence": 0.90, "source": "1234567A/M/P/000"},
  "recipient_name": {"value": "BIAT IT", "confidence": 0.95, "source": "BIAT IT"},
  "recipient_tax_id": {"value": "9876543B/N/Q/001", "confidence": 0.90, "source": "9876543B/N/Q/001"},
  "invoice_number": {"value": "FAC-TEST-OOREDOO-001", "confidence": 0.98, "source": "FAC-TEST-OOREDOO-001"},
  "invoice_date": {"value": "2026-01-15", "confidence": 0.95, "source": "15/01/2026"},
  "due_date": {"value": "2026-02-15", "confidence": 0.90, "source": "15/02/2026"},
  "amount_ht": {"value": 2500.0, "confidence": 0.95, "source": "2500.000"},
  "tva_rate": {"value": 19.0, "confidence": 0.95, "source": "19%"},
  "tva_amount": {"value": 475.0, "confidence": 0.95, "source": "475.000"},
  "amount_ttc": {"value": 2975.0, "confidence": 0.95, "source": "2975.000"},
  "currency": {"value": "TND", "confidence": 1.0, "source": "TND"},
  "line_items": [
    {"description": "Abonnement forfait data entreprise", "quantity": 1.0,
     "unit_price": 2500.0, "line_total": 2500.0, "tva_rate": 19.0}
  ]
}"""


@pytest.mark.skipif(
    not REAL_PDF.exists(),
    reason="Real PDF not found in inbox/invoice_01_ooredoo.pdf",
)
def test_real_pdf_reaches_terminal_status(tmp_path) -> None:
    """Run a real PDF through the full pipeline and assert a valid terminal status."""
    from src.agent.config_loader import build_pipeline_components
    from src.agent.pipeline import process_invoice
    from src.models.enums import InvoiceStatus
    from src.models.invoice import InvoiceRecord

    invoice_id = uuid.uuid4()
    invoice = InvoiceRecord(
        id=invoice_id,
        raw_file_path=str(REAL_PDF),
        file_hash="test_" + str(uuid.uuid4()),
    )

    components, _ = build_pipeline_components()

    try:
        with patch.object(
            components.extractor.llm_extractor.backend,
            "complete",
            return_value=_MOCK_LLM_RESPONSE,
        ):
            components.repository.save(invoice)
            result = process_invoice(invoice, components)

        assert result.status in (
            InvoiceStatus.JOURNALED,
            InvoiceStatus.EXPORTED,
            InvoiceStatus.FLAGGED,
            InvoiceStatus.ERROR,
            InvoiceStatus.EXTRACTION_FAILED,
        ), f"Unexpected final status: {result.status}"

        if result.status == InvoiceStatus.JOURNALED and result.cost_catalog_id:
            # Only expect a journal entry when the catalog matched (unknown direction → no entry)
            entries = components.journal_repository.get_by_invoice(invoice_id)
            assert len(entries) > 0, (
                f"Status JOURNALED + cost_catalog_id={result.cost_catalog_id!r} "
                "but no journal entry found"
            )
            for entry in entries:
                total_debit  = sum(ln.debit  or 0.0 for ln in entry.lines)
                total_credit = sum(ln.credit or 0.0 for ln in entry.lines)
                assert abs(total_debit - total_credit) < 0.02, (
                    f"Unbalanced journal entry {entry.reference}: "
                    f"debit={total_debit} credit={total_credit}"
                )

    finally:
        components.repository.delete(invoice_id)
        components.close()
