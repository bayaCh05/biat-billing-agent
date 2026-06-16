"""Core invoice processing pipeline — pure functions, no class state.

Architecture:
  PipelineComponents  — dataclass carrying all injected dependencies
  process_invoice()   — runs one invoice through all 5 stages in sequence
  extract()           — Stage 1: PDF/OCR/LLM extraction
  classify()          — Stage 2: direction + accounting code assignment
  validate()          — Stage 3: field validation, coherence, duplicate detection
  export_file()       — Stage 4: write JSON/CSV to disk → EXPORTED
  post_journal()      — Stage 5: post double-entry journal entry → JOURNALED
  recover_interrupted()  — resets mid-flight invoices on agent startup
  re_enqueue_received()  — requeues RECEIVED invoices that survived a crash
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.extraction.invoice_validator import NotAnInvoiceError
from src.models.enums import FlagSeverity, FlagType, InvoiceStatus
from src.models.invoice import InvoiceRecord, ValidationFlag
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.accounting.entry_generator import EntryGenerator
    from src.accounting.journal_store import JournalRepository
    from src.agent.auto_corrector import AutoCorrector
    from src.billing.cost_allocator import CostAllocator
    from src.billing.monthly_invoice_builder import MonthlyInvoiceBuilder
    from src.billing.project_repository import ProjectRepository
    from src.classification.accounting_coder import AccountingCoder
    from src.classification.classifier import Classifier
    from src.cost_catalog.catalog import CostCatalog
    from src.extraction.hybrid_extractor import HybridExtractor
    from src.storage.exporters.base import ExporterBase
    from src.storage.repository import InvoiceRepository
    from src.validation.anomaly_detector import AnomalyDetector
    from src.validation.coherence_checker import CoherenceChecker
    from src.validation.duplicate_detector import DuplicateDetector
    from src.validation.escalator import FlagEscalator
    from src.validation.field_validator import FieldValidator

logger = get_logger(__name__)


# ── Components ────────────────────────────────────────────────────────────────

@dataclass
class PipelineComponents:
    """All injected dependencies for the invoice processing pipeline.

    Build with config_loader.build_pipeline_components().
    Pass to process_invoice() or any individual stage function.
    """
    # Extraction
    extractor:           "HybridExtractor"
    # Classification
    classifier:          "Classifier"
    coder:               "AccountingCoder"
    # Validation
    field_validator:     "FieldValidator"
    coherence_checker:   "CoherenceChecker"
    duplicate_detector:  "DuplicateDetector"
    anomaly_detector:    "AnomalyDetector"
    # Correction
    auto_corrector:      "AutoCorrector"
    # Export & accounting
    exporter:            "ExporterBase"
    entry_generator:     "EntryGenerator"
    cost_catalog:        "CostCatalog"
    # Storage
    repository:          "InvoiceRepository"
    journal_repository:  "JournalRepository"
    # Validation escalation (optional — omit to disable)
    escalator:               "FlagEscalator | None" = None
    # Project billing (optional — wired when project module is active)
    project_repo:            "ProjectRepository | None" = None
    cost_allocator:          "CostAllocator | None" = None
    monthly_invoice_builder: "MonthlyInvoiceBuilder | None" = None
    # Settings
    max_retries:             int = 3
    # Sessions to close on shutdown (set by config_loader)
    _sessions:               list = field(default_factory=list, repr=False)

    def close(self) -> None:
        """Close all managed DB sessions."""
        for session in self._sessions:
            try:
                session.close()
            except Exception:
                pass


# ── Constants ─────────────────────────────────────────────────────────────────

_TERMINAL_STATUSES = frozenset({
    InvoiceStatus.FLAGGED,
    InvoiceStatus.ESCALATED,
    InvoiceStatus.ERROR,
    InvoiceStatus.REJECTED,
    InvoiceStatus.EXTRACTION_FAILED,
})

_RECOVERY_MAP: dict[InvoiceStatus, InvoiceStatus] = {
    InvoiceStatus.EXTRACTING:  InvoiceStatus.RECEIVED,
    InvoiceStatus.CLASSIFYING: InvoiceStatus.EXTRACTED,
    InvoiceStatus.VALIDATING:  InvoiceStatus.CLASSIFIED,
    InvoiceStatus.EXPORTING:   InvoiceStatus.VALIDATED,
    InvoiceStatus.JOURNALING:  InvoiceStatus.EXPORTED,
}


# ── Public entry point ────────────────────────────────────────────────────────

def process_invoice(invoice: InvoiceRecord, c: PipelineComponents) -> InvoiceRecord:
    """Run one invoice through all pipeline stages.

    Returns the invoice in its final state. Stages short-circuit on any
    terminal status (FLAGGED, ERROR, etc.) or on a soft extraction failure.
    """
    for stage_fn in (extract, classify, validate, export_file, post_journal):
        invoice = stage_fn(invoice, c)
        if invoice.status in _TERMINAL_STATUSES or invoice.last_error:
            logger.info(
                "pipeline_halted_early",
                invoice_id=str(invoice.id),
                status=invoice.status.value,
                reason="terminal_status_reached",
            )
            break
    return invoice


# ── Stage functions ───────────────────────────────────────────────────────────

def extract(invoice: InvoiceRecord, c: PipelineComponents) -> InvoiceRecord:
    """Stage 1 — PDF/OCR/LLM field extraction.

    NotAnInvoiceError is handled here directly (not via _run_stage) so that:
      - invoice.last_error is always set, letting the Streamlit app stop early
      - No retry loop is entered for a categorical rejection
    """
    invoice.status = InvoiceStatus.EXTRACTING
    c.repository.save(invoice)
    logger.info("stage_started", invoice_id=str(invoice.id), status=InvoiceStatus.EXTRACTING)

    try:
        invoice = c.extractor.extract(invoice)

    except NotAnInvoiceError as e:
        logger.error("not_an_invoice_rejected",
                     invoice_id=str(invoice.id),
                     reason=e.reason)
        invoice.add_flag(ValidationFlag(
            flag_type=FlagType.NOT_AN_INVOICE,
            severity=FlagSeverity.ERROR,
            message=(
                f"Document rejeté: {e.reason}. "
                "Ce fichier n'est pas une facture."
            ),
        ))
        invoice.status    = InvoiceStatus.ERROR
        invoice.last_error = f"Not an invoice: {e.reason}"
        c.repository.save(invoice)
        return invoice

    except Exception as exc:
        invoice.retry_count += 1
        invoice.last_error = str(exc)
        if invoice.retry_count < c.max_retries:
            invoice.status = _RECOVERY_MAP.get(
                InvoiceStatus.EXTRACTING, InvoiceStatus.EXTRACTION_FAILED
            )
            logger.warning("stage_failed_retrying",
                           invoice_id=str(invoice.id),
                           attempt=invoice.retry_count,
                           error=str(exc))
        else:
            invoice.status = InvoiceStatus.EXTRACTION_FAILED
            logger.error("stage_failed_max_retries",
                         invoice_id=str(invoice.id),
                         error=str(exc))
        c.repository.save(invoice)
        return invoice

    # ── Success ───────────────────────────────────────────────────────────────
    invoice.status = InvoiceStatus.EXTRACTED
    invoice.updated_at = datetime.now(timezone.utc)
    c.repository.save(invoice)
    logger.info("stage_completed", invoice_id=str(invoice.id), status=InvoiceStatus.EXTRACTED)
    return invoice


def classify(invoice: InvoiceRecord, c: PipelineComponents) -> InvoiceRecord:
    """Stage 2 — direction classification + accounting code assignment."""
    def _classify(inv: InvoiceRecord) -> InvoiceRecord:
        inv = c.classifier.classify(inv)
        inv = c.coder.assign(inv)
        inv.classified_at = datetime.now(timezone.utc)
        return inv

    return _run_stage(
        invoice, c,
        entering=InvoiceStatus.CLASSIFYING,
        success=InvoiceStatus.CLASSIFIED,
        failure=InvoiceStatus.ERROR,
        fn=_classify,
    )


def validate(invoice: InvoiceRecord, c: PipelineComponents) -> InvoiceRecord:
    """Stage 3 — field validation, coherence, duplicate detection, auto-correction."""
    def _validate(inv: InvoiceRecord) -> InvoiceRecord:
        inv = c.field_validator.validate(inv)
        inv = c.coherence_checker.check(inv)
        inv = c.duplicate_detector.detect(inv)
        inv = c.anomaly_detector.detect(inv)
        if c.escalator:
            inv = c.escalator.escalate(inv)
        inv.validated_at = datetime.now(timezone.utc)
        inv.status = InvoiceStatus.FLAGGED if inv.has_errors else InvoiceStatus.VALIDATED
        if inv.status == InvoiceStatus.FLAGGED and c.auto_corrector:
            inv = c.auto_corrector.correct(inv)
        return inv

    # success=None because _validate sets the status itself
    return _run_stage(
        invoice, c,
        entering=InvoiceStatus.VALIDATING,
        success=None,
        failure=InvoiceStatus.ERROR,
        fn=_validate,
    )


def export_file(invoice: InvoiceRecord, c: PipelineComponents) -> InvoiceRecord:
    """Stage 4 — write invoice to JSON/CSV on disk."""
    def _do_export(inv: InvoiceRecord) -> InvoiceRecord:
        ref = c.exporter.export(inv)
        inv.export_reference = ref
        inv.exported_at = datetime.now(timezone.utc)
        return inv

    return _run_stage(
        invoice, c,
        entering=InvoiceStatus.EXPORTING,
        success=InvoiceStatus.EXPORTED,
        failure=InvoiceStatus.ERROR,
        fn=_do_export,
    )


def post_journal(invoice: InvoiceRecord, c: PipelineComponents) -> InvoiceRecord:
    """Stage 5 — post double-entry journal entry for the exported invoice.

    On success: EXPORTED → JOURNALING → JOURNALED.
    On failure: reverts to EXPORTED + JOURNAL_FAILED ERROR flag.
    Not retried via _run_stage — an unbalanced entry won't fix itself.
    """
    invoice.status = InvoiceStatus.JOURNALING
    c.repository.save(invoice)
    logger.info("stage_started", invoice_id=str(invoice.id), status=InvoiceStatus.JOURNALING)

    try:
        _post_journal_entry(invoice, c)
        invoice.status = InvoiceStatus.JOURNALED
        invoice.updated_at = datetime.now(timezone.utc)
        c.repository.save(invoice)
        logger.info("stage_completed", invoice_id=str(invoice.id), status=invoice.status)
    except Exception as exc:
        invoice.status = InvoiceStatus.EXPORTED  # file is on disk; revert journal attempt
        invoice.add_flag(ValidationFlag(
            flag_type=FlagType.JOURNAL_FAILED,
            severity=FlagSeverity.ERROR,
            field_name="journal",
            message=str(exc),
        ))
        invoice.last_error = str(exc)
        invoice.updated_at = datetime.now(timezone.utc)
        c.repository.save(invoice)
        logger.error("journal_stage_failed", invoice_id=str(invoice.id), error=str(exc))

    return invoice


# ── Recovery ──────────────────────────────────────────────────────────────────

def recover_interrupted(repository: "InvoiceRepository") -> None:
    """Reset mid-flight invoices on startup and run one-time startup migrations."""
    # Reset transition states to their last stable state
    for interrupted, reset in _RECOVERY_MAP.items():
        for inv in repository.get_by_status(interrupted):
            inv.status = reset
            repository.save(inv)
            logger.info("recovered_invoice", invoice_id=str(inv.id), reset_to=reset)

    # One-time migration: promote EXPORTED invoices that have no JOURNAL_FAILED flag
    # to JOURNALED — these were successfully exported before the journal stage split
    # was introduced and are safe to treat as already journaled.
    for inv in repository.get_by_status(InvoiceStatus.EXPORTED):
        has_journal_failed = any(
            f.flag_type == FlagType.JOURNAL_FAILED for f in inv.flags
        )
        if not has_journal_failed:
            inv.status = InvoiceStatus.JOURNALED
            repository.save(inv)
            logger.info("migrated_exported_to_journaled", invoice_id=str(inv.id))


def re_enqueue_received(repository: "InvoiceRepository", ingestor) -> None:
    """Re-queue RECEIVED invoices so they aren't lost across restarts."""
    for inv in repository.get_by_status(InvoiceStatus.RECEIVED):
        ingestor.enqueue(inv)
        logger.info("requeued_received_invoice", invoice_id=str(inv.id))


# ── Internal stage runner ─────────────────────────────────────────────────────

def _run_stage(
    invoice: InvoiceRecord,
    c: PipelineComponents,
    *,
    entering: InvoiceStatus,
    success: InvoiceStatus | None,
    failure: InvoiceStatus,
    fn,
) -> InvoiceRecord:
    invoice.status = entering
    c.repository.save(invoice)
    logger.info("stage_started", invoice_id=str(invoice.id), status=entering)

    try:
        invoice = fn(invoice)
        if success is not None:
            invoice.status = success
        invoice.updated_at = datetime.now(timezone.utc)
        c.repository.save(invoice)
        logger.info("stage_completed", invoice_id=str(invoice.id), status=invoice.status)
    except Exception as exc:
        invoice.retry_count += 1
        invoice.last_error = str(exc)
        if invoice.retry_count < c.max_retries:
            invoice.status = _RECOVERY_MAP.get(entering, failure)
            logger.warning(
                "stage_failed_retrying",
                invoice_id=str(invoice.id),
                attempt=invoice.retry_count,
                error=str(exc),
            )
        else:
            invoice.status = failure
            logger.error(
                "stage_failed_max_retries",
                invoice_id=str(invoice.id),
                error=str(exc),
            )
        c.repository.save(invoice)

    return invoice


# ── Journal helper ────────────────────────────────────────────────────────────

def _post_journal_entry(invoice: InvoiceRecord, c: PipelineComponents) -> None:
    """Generate and save the journal entry. Raises on failure — caller handles status."""
    if not invoice.cost_catalog_id:
        return
    catalog_entry = c.cost_catalog.get(invoice.cost_catalog_id) if c.cost_catalog else None
    if catalog_entry is None:
        logger.warning(
            "journal_entry_skipped_no_catalog",
            invoice_id=str(invoice.id),
            catalog_id=invoice.cost_catalog_id,
        )
        return
    entry = c.entry_generator.generate(invoice, catalog_entry)
    c.journal_repository.save(entry)
    logger.info("journal_entry_created", invoice_id=str(invoice.id), reference=entry.reference)
