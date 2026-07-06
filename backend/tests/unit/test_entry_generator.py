"""Tests unitaires du générateur d'écritures comptables."""
from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from src.accounting.entry_generator import EntryGenerationError, EntryGenerator
from src.accounting.plan_comptable import ComptesTiers, ComptesTVA
from src.cost_catalog.catalog import CostCatalogEntry
from src.models.enums import ChargeFlux, ChargeNature, ChargeType, Recurrence
from src.models.invoice import ConfidenceField, InvoiceRecord


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_invoice(
    ht: float | None = 1000.0,
    tva: float | None = 190.0,
    ttc: float | None = 1190.0,
    tva_rate: float | None = 19.0,
    issuer: str = "Société Fournisseur SARL",
    recipient: str = "BIAT IT",
    invoice_number: str = "FAC-2024-001",
    invoice_date: date = date(2024, 3, 15),
) -> InvoiceRecord:
    inv = InvoiceRecord(
        file_hash="testhash001",
        raw_file_path="/tmp/test.pdf",
    )
    inv.amount_ht = ConfidenceField(value=ht, confidence=0.95)
    inv.tva_amount = ConfidenceField(value=tva, confidence=0.95)
    inv.amount_ttc = ConfidenceField(value=ttc, confidence=0.95)
    inv.tva_rate = ConfidenceField(value=tva_rate, confidence=0.95)
    inv.issuer_name = ConfidenceField(value=issuer, confidence=0.95)
    inv.recipient_name = ConfidenceField(value=recipient, confidence=0.95)
    inv.invoice_number = ConfidenceField(value=invoice_number, confidence=0.95)
    inv.invoice_date = ConfidenceField(value=invoice_date, confidence=0.95)
    return inv


def _catalog_entry(
    entry_id: str = "maintenance_informatique",
    compte: str = "6112",
    label: str = "Maintenance et support informatique",
    flux: ChargeFlux = ChargeFlux.FOURNISSEUR,
    type_charge: ChargeType = ChargeType.OPEX,
) -> CostCatalogEntry:
    return CostCatalogEntry(
        id=entry_id,
        label=label,
        compte=compte,
        nature=ChargeNature.FIXE,
        type_charge=type_charge,
        tva_rate=19.0,
        recurrence=Recurrence.MENSUELLE,
        flux=flux,
        keywords=["maintenance"],
    )


@pytest.fixture
def generator() -> EntryGenerator:
    return EntryGenerator()


# ── Factures fournisseur ──────────────────────────────────────────────────────

class TestFournisseurEntry:
    def test_opex_with_tva_structure(self, generator):
        inv = _make_invoice()
        entry = generator.generate(inv, _catalog_entry())

        assert entry.is_balanced
        comptes = [l.compte for l in entry.lines]
        assert "6112" in comptes
        assert ComptesTVA.TVA_DEDUCTIBLE in comptes
        assert ComptesTiers.FOURNISSEURS in comptes

    def test_opex_debit_amounts(self, generator):
        inv = _make_invoice(ht=1000.0, tva=190.0, ttc=1190.0)
        entry = generator.generate(inv, _catalog_entry())

        charge_line = next(l for l in entry.lines if l.compte == "6112")
        tva_line = next(l for l in entry.lines if l.compte == ComptesTVA.TVA_DEDUCTIBLE)
        fournisseur_line = next(l for l in entry.lines if l.compte == ComptesTiers.FOURNISSEURS)

        assert charge_line.debit == 1000.0
        assert tva_line.debit == 190.0
        assert fournisseur_line.credit == 1190.0

    def test_capex_uses_immobilisation_account(self, generator):
        inv = _make_invoice(ht=5000.0, tva=950.0, ttc=5950.0)
        capex_entry = _catalog_entry(
            entry_id="materiel_informatique",
            compte="2183",
            label="Matériel informatique",
            type_charge=ChargeType.CAPEX,
        )
        entry = generator.generate(inv, capex_entry)

        comptes = [l.compte for l in entry.lines]
        assert "2183" in comptes                       # immobilisation CAPEX
        assert ComptesTVA.TVA_DEDUCTIBLE in comptes
        assert ComptesTiers.FOURNISSEURS in comptes

    def test_no_tva_two_lines_only(self, generator):
        # TVA = 0 → seulement 2 lignes (charge + fournisseur)
        inv = _make_invoice(ht=5000.0, tva=0.0, ttc=5000.0, tva_rate=0.0)
        entry = generator.generate(inv, _catalog_entry())

        assert len(entry.lines) == 2
        assert ComptesTVA.TVA_DEDUCTIBLE not in [l.compte for l in entry.lines]

    def test_no_tva_amounts_balanced(self, generator):
        inv = _make_invoice(ht=2500.0, tva=0.0, ttc=2500.0, tva_rate=0.0)
        entry = generator.generate(inv, _catalog_entry())

        assert entry.total_debit == 2500.0
        assert entry.total_credit == 2500.0

    def test_reference_from_invoice_number(self, generator):
        inv = _make_invoice(invoice_number="FAC-TEST-999")
        entry = generator.generate(inv, _catalog_entry())
        assert "FAC-TEST-999" in entry.reference

    def test_date_from_invoice_date(self, generator):
        inv = _make_invoice(invoice_date=date(2024, 6, 1))
        entry = generator.generate(inv, _catalog_entry())
        assert entry.date_ecriture == date(2024, 6, 1)

    def test_source_invoice_id_set(self, generator):
        inv = _make_invoice()
        entry = generator.generate(inv, _catalog_entry())
        assert entry.source_invoice_id == inv.id

    def test_issuer_name_in_fournisseur_libelle(self, generator):
        inv = _make_invoice(issuer="Dell Technologies Tunisia")
        entry = generator.generate(inv, _catalog_entry())
        fournisseur_line = next(l for l in entry.lines if l.compte == ComptesTiers.FOURNISSEURS)
        assert "Dell Technologies Tunisia" in fournisseur_line.libelle


# ── Factures client ───────────────────────────────────────────────────────────

class TestClientEntry:
    def _client_catalog(self) -> CostCatalogEntry:
        return _catalog_entry(
            entry_id="prestations_si",
            compte="7061",
            label="Prestations de services informatiques",
            flux=ChargeFlux.CLIENT,
        )

    def test_client_with_tva_structure(self, generator):
        inv = _make_invoice()
        entry = generator.generate(inv, self._client_catalog())

        comptes = [l.compte for l in entry.lines]
        assert ComptesTiers.CLIENTS in comptes
        assert "7061" in comptes
        assert ComptesTVA.TVA_COLLECTEE in comptes

    def test_client_debit_is_ttc(self, generator):
        inv = _make_invoice(ht=1000.0, tva=190.0, ttc=1190.0)
        entry = generator.generate(inv, self._client_catalog())

        client_line = next(l for l in entry.lines if l.compte == ComptesTiers.CLIENTS)
        assert client_line.debit == 1190.0

    def test_client_credit_ht_plus_tva(self, generator):
        inv = _make_invoice(ht=1000.0, tva=190.0, ttc=1190.0)
        entry = generator.generate(inv, self._client_catalog())

        produit_line = next(l for l in entry.lines if l.compte == "7061")
        tva_line = next(l for l in entry.lines if l.compte == ComptesTVA.TVA_COLLECTEE)

        assert produit_line.credit == 1000.0
        assert tva_line.credit == 190.0

    def test_client_no_tva_two_lines(self, generator):
        inv = _make_invoice(ht=3000.0, tva=0.0, ttc=3000.0, tva_rate=0.0)
        entry = generator.generate(inv, self._client_catalog())

        assert len(entry.lines) == 2
        assert ComptesTVA.TVA_COLLECTEE not in [l.compte for l in entry.lines]

    def test_client_entry_balanced(self, generator):
        inv = _make_invoice(ht=2000.0, tva=380.0, ttc=2380.0)
        entry = generator.generate(inv, self._client_catalog())
        assert entry.is_balanced


# ── Cas d'erreur ─────────────────────────────────────────────────────────────

class TestEntryGenerationErrors:
    def test_missing_ht_raises(self, generator):
        inv = _make_invoice(ht=None)
        with pytest.raises(EntryGenerationError, match="montants non extraits"):
            generator.generate(inv, _catalog_entry())

    def test_missing_ttc_raises(self, generator):
        inv = _make_invoice(ttc=None)
        with pytest.raises(EntryGenerationError, match="montants non extraits"):
            generator.generate(inv, _catalog_entry())

    def test_interne_flux_raises(self, generator):
        inv = _make_invoice()
        interne_entry = _catalog_entry(flux=ChargeFlux.INTERNE)
        with pytest.raises(EntryGenerationError, match="non supporté"):
            generator.generate(inv, interne_entry)

    def test_tva_none_treated_as_zero(self, generator):
        # TVA None doit être traité comme 0 (pas d'erreur)
        inv = _make_invoice(ht=500.0, tva=None, ttc=500.0)
        entry = generator.generate(inv, _catalog_entry())
        assert entry.is_balanced
        assert len(entry.lines) == 2  # pas de ligne TVA
