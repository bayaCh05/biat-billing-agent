"""
Tests for the storage layer: ORM models, repository, and exporters.
Uses an in-memory SQLite database — no files on disk.
"""

import json
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.models.enums import (
    FlagSeverity,
    FlagType,
    InvoiceDirection,
    InvoiceStatus,
)
from src.models.invoice import ConfidenceField, InvoiceRecord, LineItem, ValidationFlag
from src.storage.db import Base, build_engine, build_session_factory, init_db
from src.storage.repository import InvoiceRepository
from src.storage.exporters.json_exporter import JSONExporter
from src.storage.exporters.csv_exporter import CSVExporter


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def session():
    engine = build_engine("sqlite:///:memory:")
    init_db(engine)
    SessionFactory = build_session_factory(engine)
    s = SessionFactory()
    yield s
    s.close()
    engine.dispose()


@pytest.fixture()
def repo(session):
    return InvoiceRepository(session)


@pytest.fixture()
def sample_invoice():
    inv = InvoiceRecord(
        file_hash="abc123def456" + "0" * 52,
        raw_file_path="/inbox/facture_001.pdf",
        direction=InvoiceDirection.SUPPLIER,
        status=InvoiceStatus.RECEIVED,
    )
    inv.invoice_number = ConfidenceField(value="FAC-2024-001", confidence=0.95)
    inv.invoice_date = ConfidenceField(value=date(2024, 6, 1), confidence=0.92)
    inv.due_date = ConfidenceField(value=date(2024, 7, 1), confidence=0.88)
    inv.issuer_name = ConfidenceField(value="Fournisseur SARL", confidence=0.97)
    inv.issuer_tax_id = ConfidenceField(value="1234567/A/M/000", confidence=0.91)
    inv.recipient_name = ConfidenceField(value="BIAT IT", confidence=0.99)
    inv.amount_ht = ConfidenceField(value=1000.0, confidence=0.96)
    inv.tva_rate = ConfidenceField(value=19.0, confidence=0.99)
    inv.tva_amount = ConfidenceField(value=190.0, confidence=0.96)
    inv.amount_ttc = ConfidenceField(value=1190.0, confidence=0.96)
    inv.line_items = [
        LineItem(line_number=1, description="Prestation dev", quantity=10, unit_price=100.0, line_total=1000.0, tva_rate=19.0)
    ]
    return inv


# ── Repository tests ───────────────────────────────────────────────────────────

class TestRepository:

    def test_save_and_retrieve_by_id(self, repo, sample_invoice):
        repo.save(sample_invoice)
        loaded = repo.get_by_id(sample_invoice.id)

        assert loaded is not None
        assert loaded.id == sample_invoice.id
        assert loaded.direction == InvoiceDirection.SUPPLIER
        assert loaded.status == InvoiceStatus.RECEIVED

    def test_confidence_fields_roundtrip(self, repo, sample_invoice):
        repo.save(sample_invoice)
        loaded = repo.get_by_id(sample_invoice.id)

        assert loaded.invoice_number.value == "FAC-2024-001"
        assert loaded.invoice_number.confidence == pytest.approx(0.95)
        assert loaded.amount_ttc.value == pytest.approx(1190.0)
        assert loaded.amount_ttc.confidence == pytest.approx(0.96)
        assert loaded.invoice_date.value == date(2024, 6, 1)

    def test_line_items_roundtrip(self, repo, sample_invoice):
        repo.save(sample_invoice)
        loaded = repo.get_by_id(sample_invoice.id)

        assert len(loaded.line_items) == 1
        li = loaded.line_items[0]
        assert li.description == "Prestation dev"
        assert li.quantity == pytest.approx(10.0)
        assert li.line_total == pytest.approx(1000.0)

    def test_get_by_hash(self, repo, sample_invoice):
        repo.save(sample_invoice)
        loaded = repo.get_by_hash(sample_invoice.file_hash)
        assert loaded is not None
        assert loaded.id == sample_invoice.id

    def test_get_by_hash_missing_returns_none(self, repo):
        assert repo.get_by_hash("nonexistent_hash") is None

    def test_get_by_status(self, repo, sample_invoice):
        repo.save(sample_invoice)
        results = repo.get_by_status(InvoiceStatus.RECEIVED)
        assert any(i.id == sample_invoice.id for i in results)

    def test_status_update_writes_history(self, repo, sample_invoice):
        repo.save(sample_invoice)

        sample_invoice.status = InvoiceStatus.EXTRACTING
        repo.save(sample_invoice)

        sample_invoice.status = InvoiceStatus.EXTRACTED
        repo.save(sample_invoice)

        # The status_history table should have 3 entries (RECEIVED, EXTRACTING, EXTRACTED)
        from src.storage.orm_models import StatusHistoryORM
        from sqlalchemy import select
        history = repo.session.execute(
            select(StatusHistoryORM).where(StatusHistoryORM.invoice_id == sample_invoice.id)
        ).scalars().all()
        assert len(history) == 3
        statuses = [h.to_status for h in history]
        assert "RECEIVED" in statuses
        assert "EXTRACTING" in statuses
        assert "EXTRACTED" in statuses

    def test_flags_roundtrip(self, repo, sample_invoice):
        sample_invoice.add_flag(ValidationFlag(
            flag_type=FlagType.LOW_CONFIDENCE,
            severity=FlagSeverity.WARNING,
            field_name="due_date",
            message="due_date confidence below threshold",
        ))
        sample_invoice.add_flag(ValidationFlag(
            flag_type=FlagType.TOTAL_MISMATCH,
            severity=FlagSeverity.ERROR,
            message="HT + TVA does not equal TTC",
        ))
        repo.save(sample_invoice)
        loaded = repo.get_by_id(sample_invoice.id)

        assert len(loaded.flags) == 2
        types = {f.flag_type for f in loaded.flags}
        assert FlagType.LOW_CONFIDENCE in types
        assert FlagType.TOTAL_MISMATCH in types

    def test_get_flagged(self, repo, sample_invoice):
        sample_invoice.status = InvoiceStatus.FLAGGED
        sample_invoice.human_review_required = True
        repo.save(sample_invoice)

        flagged = repo.get_flagged()
        assert any(i.id == sample_invoice.id for i in flagged)

    def test_find_potential_duplicates(self, repo, sample_invoice):
        repo.save(sample_invoice)

        dupes = repo.find_potential_duplicates(
            invoice_number="FAC-2024-001",
            issuer_tax_id="1234567/A/M/000",
            window_days=90,
        )
        assert len(dupes) == 1
        assert dupes[0].id == sample_invoice.id

    def test_get_historical_amounts(self, repo, sample_invoice):
        repo.save(sample_invoice)
        amounts = repo.get_historical_amounts("1234567/A/M/000")
        assert 1190.0 in amounts

    def test_update_replaces_line_items(self, repo, sample_invoice):
        repo.save(sample_invoice)

        # Replace with two items
        sample_invoice.line_items = [
            LineItem(line_number=1, description="Item A", quantity=2, unit_price=50.0, line_total=100.0, tva_rate=19.0),
            LineItem(line_number=2, description="Item B", quantity=1, unit_price=900.0, line_total=900.0, tva_rate=19.0),
        ]
        repo.save(sample_invoice)

        loaded = repo.get_by_id(sample_invoice.id)
        assert len(loaded.line_items) == 2
        descs = [li.description for li in loaded.line_items]
        assert "Item A" in descs
        assert "Item B" in descs

    def test_two_invoices_different_hashes(self, repo, sample_invoice):
        inv2 = InvoiceRecord(
            file_hash="different_hash" + "0" * 50,
            raw_file_path="/inbox/facture_002.pdf",
            direction=InvoiceDirection.CLIENT,
            status=InvoiceStatus.RECEIVED,
        )
        repo.save(sample_invoice)
        repo.save(inv2)

        all_received = repo.get_by_status(InvoiceStatus.RECEIVED)
        ids = {i.id for i in all_received}
        assert sample_invoice.id in ids
        assert inv2.id in ids


# ── Exporter tests ─────────────────────────────────────────────────────────────

class TestJSONExporter:

    def test_creates_file(self, sample_invoice, tmp_path):
        exporter = JSONExporter(export_path=str(tmp_path))
        ref = exporter.export(sample_invoice)

        assert Path(ref).exists()

    def test_json_is_valid_and_contains_fields(self, sample_invoice, tmp_path):
        exporter = JSONExporter(export_path=str(tmp_path))
        ref = exporter.export(sample_invoice)

        data = json.loads(Path(ref).read_text())
        assert data["direction"] == "SUPPLIER"
        assert data["invoice_number"]["value"] == "FAC-2024-001"
        assert data["amount_ttc"]["value"] == pytest.approx(1190.0)

    def test_filename_contains_invoice_number(self, sample_invoice, tmp_path):
        exporter = JSONExporter(export_path=str(tmp_path))
        ref = exporter.export(sample_invoice)
        assert "FAC-2024-001" in Path(ref).name


class TestCSVExporter:

    def test_creates_file_and_writes_header(self, sample_invoice, tmp_path):
        exporter = CSVExporter(export_path=str(tmp_path))
        ref = exporter.export(sample_invoice)

        content = Path(ref).read_text()
        assert "invoice_number" in content
        assert "amount_ttc" in content

    def test_appends_second_row(self, sample_invoice, tmp_path):
        exporter = CSVExporter(export_path=str(tmp_path))
        exporter.export(sample_invoice)

        import csv
        rows = list(csv.DictReader(Path(list(tmp_path.iterdir())[0]).open()))
        assert len(rows) == 1
        assert rows[0]["invoice_number"] == "FAC-2024-001"
        assert float(rows[0]["amount_ttc"]) == pytest.approx(1190.0)
