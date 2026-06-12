"""Tests unitaires des modèles JournalLine et JournalEntry."""
from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from src.models.journal import JournalEntry, JournalLine


# ── JournalLine ───────────────────────────────────────────────────────────────

class TestJournalLine:
    def test_debit_only_valid(self):
        line = JournalLine(compte="6112", libelle="Maintenance", debit=1000.0)
        assert line.debit == 1000.0
        assert line.credit is None

    def test_credit_only_valid(self):
        line = JournalLine(compte="401", libelle="Fournisseur", credit=1190.0)
        assert line.credit == 1190.0
        assert line.debit is None

    def test_both_debit_and_credit_raises(self):
        with pytest.raises(ValueError, match="exactement un montant"):
            JournalLine(compte="401", libelle="Test", debit=100.0, credit=100.0)

    def test_neither_debit_nor_credit_raises(self):
        with pytest.raises(ValueError, match="exactement un montant"):
            JournalLine(compte="401", libelle="Test")


# ── JournalEntry ──────────────────────────────────────────────────────────────

def _supplier_entry(**kwargs) -> JournalEntry:
    """Écriture fournisseur standard équilibrée : 1000 HT + 190 TVA = 1190 TTC."""
    defaults = dict(
        reference="FAC-2024-001",
        date_ecriture=date(2024, 3, 15),
        description="Facture fournisseur test",
        lines=[
            JournalLine(compte="6112", libelle="Maintenance", debit=1000.0),
            JournalLine(compte="4366", libelle="TVA déductible", debit=190.0),
            JournalLine(compte="401", libelle="Fournisseur X", credit=1190.0),
        ],
    )
    defaults.update(kwargs)
    return JournalEntry(**defaults)


class TestJournalEntry:
    def test_balanced_entry_creates_successfully(self):
        entry = _supplier_entry()
        assert entry.is_balanced

    def test_total_debit(self):
        entry = _supplier_entry()
        assert entry.total_debit == 1190.0

    def test_total_credit(self):
        entry = _supplier_entry()
        assert entry.total_credit == 1190.0

    def test_unbalanced_entry_raises(self):
        with pytest.raises(ValueError, match="non équilibrée"):
            JournalEntry(
                reference="BAD-001",
                date_ecriture=date(2024, 1, 1),
                description="Écriture non équilibrée",
                lines=[
                    JournalLine(compte="6112", libelle="Charge", debit=1000.0),
                    JournalLine(compte="401", libelle="Fournisseur", credit=999.0),
                ],
            )

    def test_single_line_raises(self):
        with pytest.raises(Exception):  # min_length=2
            JournalEntry(
                reference="SINGLE-001",
                date_ecriture=date(2024, 1, 1),
                description="Ligne unique",
                lines=[JournalLine(compte="6112", libelle="Charge", debit=100.0)],
            )

    def test_balance_tolerance_accepted(self):
        # Différence de 0.003 TND (dans la tolérance de 0.005)
        entry = JournalEntry(
            reference="TOL-001",
            date_ecriture=date(2024, 1, 1),
            description="Écriture avec arrondi",
            lines=[
                JournalLine(compte="6112", libelle="Charge", debit=1000.001),
                JournalLine(compte="401", libelle="Fournisseur", credit=1000.003),
            ],
        )
        assert entry.is_balanced

    def test_source_invoice_id_optional(self):
        entry = _supplier_entry(source_invoice_id=None)
        assert entry.source_invoice_id is None

    def test_source_invoice_id_set(self):
        inv_id = uuid4()
        entry = _supplier_entry(source_invoice_id=inv_id)
        assert entry.source_invoice_id == inv_id

    def test_client_entry_balanced(self):
        # Facture client : 1000 HT + 190 TVA = 1190 TTC
        entry = JournalEntry(
            reference="FACT-CLI-001",
            date_ecriture=date(2024, 3, 15),
            description="Facture client test",
            lines=[
                JournalLine(compte="411", libelle="Client BIAT", debit=1190.0),
                JournalLine(compte="7061", libelle="Prestations SI", credit=1000.0),
                JournalLine(compte="4367", libelle="TVA collectée", credit=190.0),
            ],
        )
        assert entry.is_balanced
        assert entry.total_debit == 1190.0
        assert entry.total_credit == 1190.0

    def test_no_tva_entry_balanced(self):
        # Facture sans TVA (assurance, loyer) : débit = crédit = HT
        entry = JournalEntry(
            reference="ASSUR-001",
            date_ecriture=date(2024, 1, 1),
            description="Prime assurance",
            lines=[
                JournalLine(compte="6161", libelle="Assurance multirisques", debit=5000.0),
                JournalLine(compte="401", libelle="Assureur", credit=5000.0),
            ],
        )
        assert entry.is_balanced


# ── JournalRepository ─────────────────────────────────────────────────────────

import pytest
from src.accounting.journal_store import JournalRepository
from src.storage.db import build_engine, build_session_factory, init_db


@pytest.fixture()
def journal_repo():
    engine = build_engine("sqlite:///:memory:")
    init_db(engine)
    session = build_session_factory(engine)()
    yield JournalRepository(session)
    session.close()
    engine.dispose()


def _entry(ref: str, d: "date"):
    from uuid import uuid4
    return JournalEntry(
        reference=ref,
        date_ecriture=d,
        description=f"Test entry {ref}",
        lines=[
            JournalLine(compte="6112", libelle="Charge", debit=1000.0),
            JournalLine(compte="401", libelle="Fournisseur", credit=1000.0),
        ],
    )


class TestListEntries:
    def test_empty_returns_empty_list(self, journal_repo):
        assert journal_repo.list_entries() == []

    def test_returns_all_entries(self, journal_repo):
        journal_repo.save(_entry("REF-001", date(2024, 1, 1)))
        journal_repo.save(_entry("REF-002", date(2024, 1, 2)))
        entries = journal_repo.list_entries()
        assert len(entries) == 2

    def test_ordered_by_date_descending(self, journal_repo):
        journal_repo.save(_entry("REF-A", date(2024, 1, 1)))
        journal_repo.save(_entry("REF-B", date(2024, 3, 1)))
        journal_repo.save(_entry("REF-C", date(2024, 2, 1)))
        entries = journal_repo.list_entries()
        dates = [e.date_ecriture for e in entries]
        assert dates == sorted(dates, reverse=True)

    def test_limit_respected(self, journal_repo):
        for i in range(5):
            journal_repo.save(_entry(f"REF-{i:03}", date(2024, 1, i + 1)))
        entries = journal_repo.list_entries(limit=2)
        assert len(entries) == 2

    def test_offset_respected(self, journal_repo):
        for i in range(4):
            journal_repo.save(_entry(f"REF-{i:03}", date(2024, 1, i + 1)))
        all_entries = journal_repo.list_entries()
        paged = journal_repo.list_entries(offset=2)
        assert len(paged) == 2
        assert paged[0].reference == all_entries[2].reference

    def test_limit_and_offset_combined(self, journal_repo):
        for i in range(6):
            journal_repo.save(_entry(f"REF-{i:03}", date(2024, 1, i + 1)))
        page = journal_repo.list_entries(limit=2, offset=2)
        assert len(page) == 2
