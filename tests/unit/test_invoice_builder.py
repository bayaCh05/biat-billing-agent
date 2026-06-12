"""Unit tests for InvoiceBuilder, InvoiceNumberer, TemplateLoader, PDFGenerator,
and BillingEntryGenerator."""
from __future__ import annotations

import textwrap
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.billing.billing_entry_generator import BillingEntryGenerator, BillingEntryError
from src.billing.invoice_builder import InvoiceBuilder
from src.billing.invoice_numbering import InvoiceNumberer
from src.billing.template_loader import TemplateLoader
from src.models.client_invoice import ClientInvoice, ClientInvoiceStatus


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def templates_yaml(tmp_path: Path) -> Path:
    content = textwrap.dedent("""\
        issuer:
          name:    "BIAT IT"
          tax_id:  "0000999B/A/M/000"
          address: "Lac I, Tunis"
          phone:   ""
          email:   ""
          rib:     ""

        clients:
          - id:   biat_bank
            name: "BIAT SA"
            tax_id: "0000217V/A/M/000"
            address: "70 Av. Bourguiba, Tunis"
            payment_terms_days: 30

          - id:   biat_assurances
            name: "BIAT Assurances"
            tax_id: "0000500B/A/M/000"
            address: "Lac II, Tunis"
            payment_terms_days: 45

        service_templates:
          - id:                  maintenance_si
            label:               "Maintenance SI"
            description:         "Maintenance et support SI mensuel"
            compte_produit:      "7061"
            tva_rate:            19.0
            recurrence:          mensuelle
            default_unit_price:  45000.0
            default_quantity:    1.0
            default_client_id:   biat_bank

          - id:                  formation
            label:               "Formation IT"
            description:         "Formation informatique"
            compte_produit:      "7065"
            tva_rate:            19.0
            recurrence:          ponctuelle
            default_unit_price:  2500.0
            default_quantity:    1.0
            default_client_id:   biat_bank
    """)
    p = tmp_path / "client_templates.yaml"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture
def loader(templates_yaml: Path) -> TemplateLoader:
    return TemplateLoader(templates_yaml)


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.get_max_sequence.return_value = 0
    return repo


@pytest.fixture
def numberer(mock_repo) -> InvoiceNumberer:
    return InvoiceNumberer(mock_repo)


@pytest.fixture
def builder(loader: TemplateLoader, numberer: InvoiceNumberer) -> InvoiceBuilder:
    return InvoiceBuilder(loader=loader, numberer=numberer)


# ── TemplateLoader ────────────────────────────────────────────────────────────

class TestTemplateLoader:
    def test_loads_issuer(self, loader: TemplateLoader):
        assert loader.issuer.name    == "BIAT IT"
        assert loader.issuer.tax_id  == "0000999B/A/M/000"

    def test_loads_clients(self, loader: TemplateLoader):
        clients = loader.list_clients()
        assert len(clients) == 2
        assert clients[0].id == "biat_bank"

    def test_get_client_by_id(self, loader: TemplateLoader):
        client = loader.get_client("biat_bank")
        assert client.name == "BIAT SA"
        assert client.payment_terms_days == 30

    def test_get_client_unknown_raises(self, loader: TemplateLoader):
        with pytest.raises(KeyError):
            loader.get_client("nonexistent_client")

    def test_loads_templates(self, loader: TemplateLoader):
        assert len(loader.list_templates()) == 2

    def test_get_template_by_id(self, loader: TemplateLoader):
        tmpl = loader.get_template("maintenance_si")
        assert tmpl.compte_produit    == "7061"
        assert tmpl.default_unit_price == 45000.0

    def test_get_template_unknown_raises(self, loader: TemplateLoader):
        with pytest.raises(KeyError):
            loader.get_template("does_not_exist")


# ── InvoiceNumberer ───────────────────────────────────────────────────────────

class TestInvoiceNumberer:
    def test_first_invoice_number(self, mock_repo):
        mock_repo.get_max_sequence.return_value = 0
        n = InvoiceNumberer(mock_repo).next_number(date(2026, 1, 1))
        assert n == "FAC-IT-2026-0001"

    def test_increments_correctly(self, mock_repo):
        mock_repo.get_max_sequence.return_value = 12
        n = InvoiceNumberer(mock_repo).next_number(date(2026, 6, 1))
        assert n == "FAC-IT-2026-0013"

    def test_uses_invoice_date_year(self, mock_repo):
        mock_repo.get_max_sequence.return_value = 0
        n = InvoiceNumberer(mock_repo).next_number(date(2027, 3, 15))
        assert n.startswith("FAC-IT-2027-")

    def test_parse_sequence_valid(self):
        assert InvoiceNumberer.parse_sequence("FAC-IT-2026-0042") == (2026, 42)

    def test_parse_sequence_invalid_returns_none(self):
        assert InvoiceNumberer.parse_sequence("FAC-2026-0001") is None
        assert InvoiceNumberer.parse_sequence("not-a-number")  is None


# ── InvoiceBuilder.from_template ─────────────────────────────────────────────

class TestBuildFromTemplate:
    def test_invoice_has_correct_number(self, builder: InvoiceBuilder):
        inv = builder.from_template("maintenance_si", date(2026, 1, 15))
        assert inv.invoice_number == "FAC-IT-2026-0001"

    def test_uses_default_client(self, builder: InvoiceBuilder):
        inv = builder.from_template("maintenance_si", date(2026, 1, 15))
        assert inv.client_id == "biat_bank"

    def test_overrides_client(self, builder: InvoiceBuilder):
        inv = builder.from_template("maintenance_si", date(2026, 1, 15),
                                    client_id="biat_assurances")
        assert inv.client_id == "biat_assurances"

    def test_default_unit_price(self, builder: InvoiceBuilder):
        inv = builder.from_template("maintenance_si", date(2026, 1, 15))
        assert inv.line_items[0].unit_price == pytest.approx(45000.0)

    def test_overrides_unit_price(self, builder: InvoiceBuilder):
        inv = builder.from_template("maintenance_si", date(2026, 1, 15),
                                    unit_price=50000.0)
        assert inv.line_items[0].unit_price == pytest.approx(50000.0)

    def test_overrides_quantity(self, builder: InvoiceBuilder):
        inv = builder.from_template("formation", date(2026, 1, 15), quantity=3.0)
        assert inv.line_items[0].quantity == pytest.approx(3.0)
        assert inv.line_items[0].line_total == pytest.approx(7500.0)

    def test_due_date_respects_payment_terms(self, builder: InvoiceBuilder):
        inv = builder.from_template("maintenance_si", date(2026, 1, 15))
        assert inv.due_date == date(2026, 1, 15) + timedelta(days=30)

    def test_amounts_computed_correctly(self, builder: InvoiceBuilder):
        inv = builder.from_template("maintenance_si", date(2026, 1, 15))
        assert inv.amount_ht   == pytest.approx(45000.0)
        assert inv.tva_amount  == pytest.approx(8550.0)
        assert inv.amount_ttc  == pytest.approx(53550.0)

    def test_source_template_id_set(self, builder: InvoiceBuilder):
        inv = builder.from_template("maintenance_si", date(2026, 1, 15))
        assert inv.source_template_id == "maintenance_si"

    def test_status_is_draft(self, builder: InvoiceBuilder):
        inv = builder.from_template("maintenance_si", date(2026, 1, 15))
        assert inv.status == ClientInvoiceStatus.DRAFT

    def test_notes_passed_through(self, builder: InvoiceBuilder):
        inv = builder.from_template("maintenance_si", date(2026, 1, 15),
                                    notes="Facture forfaitaire mensuelle")
        assert inv.notes == "Facture forfaitaire mensuelle"


# ── InvoiceBuilder.manual ────────────────────────────────────────────────────

class TestBuildManual:
    def test_manual_single_line(self, builder: InvoiceBuilder):
        inv = builder.manual(
            client_id="biat_bank",
            invoice_date=date(2026, 3, 1),
            line_items=[{
                "description": "Développement API",
                "quantity":    1.0,
                "unit_price":  20000.0,
                "tva_rate":    19.0,
                "compte_produit": "7062",
            }],
        )
        assert len(inv.line_items) == 1
        assert inv.line_items[0].compte_produit == "7062"
        assert inv.amount_ht == pytest.approx(20000.0)

    def test_manual_multi_line(self, builder: InvoiceBuilder):
        inv = builder.manual(
            client_id="biat_bank",
            invoice_date=date(2026, 3, 1),
            line_items=[
                {"description": "Service A", "unit_price": 10000.0},
                {"description": "Service B", "unit_price": 5000.0},
            ],
        )
        assert inv.amount_ht == pytest.approx(15000.0)

    def test_manual_uses_default_tva_rate(self, builder: InvoiceBuilder):
        inv = builder.manual(
            client_id="biat_bank",
            invoice_date=date(2026, 3, 1),
            line_items=[{"description": "Prestation", "unit_price": 10000.0}],
        )
        assert inv.line_items[0].tva_rate == pytest.approx(19.0)

    def test_manual_no_source_template(self, builder: InvoiceBuilder):
        inv = builder.manual(
            client_id="biat_bank",
            invoice_date=date(2026, 3, 1),
            line_items=[{"description": "x", "unit_price": 1000.0}],
        )
        assert inv.source_template_id is None


# ── PDFGenerator ─────────────────────────────────────────────────────────────

class TestPDFGenerator:
    @pytest.fixture
    def invoice(self, builder: InvoiceBuilder) -> ClientInvoice:
        return builder.from_template("maintenance_si", date(2026, 1, 15))

    def test_generate_to_bytes_returns_bytes(self, invoice: ClientInvoice, tmp_path: Path):
        from src.billing.pdf_generator import PDFGenerator
        gen   = PDFGenerator(output_dir=tmp_path)
        pdf_b = gen.generate_to_bytes(invoice)
        assert isinstance(pdf_b, bytes)
        assert len(pdf_b) > 1000

    def test_pdf_starts_with_pdf_magic_bytes(self, invoice: ClientInvoice, tmp_path: Path):
        from src.billing.pdf_generator import PDFGenerator
        gen   = PDFGenerator(output_dir=tmp_path)
        pdf_b = gen.generate_to_bytes(invoice)
        assert pdf_b[:4] == b"%PDF"

    def test_generate_creates_file(self, invoice: ClientInvoice, tmp_path: Path):
        from src.billing.pdf_generator import PDFGenerator
        gen  = PDFGenerator(output_dir=tmp_path)
        path = gen.generate(invoice)
        assert path.exists()
        assert path.stat().st_size > 1000

    def test_file_named_after_invoice_number(self, invoice: ClientInvoice, tmp_path: Path):
        from src.billing.pdf_generator import PDFGenerator
        gen  = PDFGenerator(output_dir=tmp_path)
        path = gen.generate(invoice)
        assert path.name == f"{invoice.invoice_number}.pdf"


# ── BillingEntryGenerator ─────────────────────────────────────────────────────

class TestBillingEntryGenerator:
    @pytest.fixture
    def invoice(self, builder: InvoiceBuilder) -> ClientInvoice:
        return builder.from_template("maintenance_si", date(2026, 1, 15))

    def test_entry_is_balanced(self, invoice: ClientInvoice):
        gen   = BillingEntryGenerator()
        entry = gen.generate(invoice)
        total_debit  = sum(l.debit  or 0 for l in entry.lines)
        total_credit = sum(l.credit or 0 for l in entry.lines)
        assert abs(total_debit - total_credit) < 0.005

    def test_entry_has_411_debit(self, invoice: ClientInvoice):
        gen   = BillingEntryGenerator()
        entry = gen.generate(invoice)
        debit_lines = [l for l in entry.lines if l.debit is not None]
        assert any(l.compte == "411" for l in debit_lines)

    def test_entry_has_4367_credit(self, invoice: ClientInvoice):
        gen   = BillingEntryGenerator()
        entry = gen.generate(invoice)
        credit_lines = [l for l in entry.lines if l.credit is not None]
        assert any(l.compte == "4367" for l in credit_lines)

    def test_entry_has_produit_credit(self, invoice: ClientInvoice):
        gen   = BillingEntryGenerator()
        entry = gen.generate(invoice)
        credit_lines = [l for l in entry.lines if l.credit is not None]
        assert any(l.compte == "7061" for l in credit_lines)

    def test_entry_reference_is_invoice_number(self, invoice: ClientInvoice):
        gen   = BillingEntryGenerator()
        entry = gen.generate(invoice)
        assert entry.reference == invoice.invoice_number

    def test_entry_date_matches_invoice(self, invoice: ClientInvoice):
        gen   = BillingEntryGenerator()
        entry = gen.generate(invoice)
        assert entry.date_ecriture == invoice.invoice_date

    def test_zero_ttc_raises_error(self, builder: InvoiceBuilder):
        inv = builder.manual(
            client_id="biat_bank",
            invoice_date=date(2026, 1, 1),
            line_items=[{"description": "x", "unit_price": 0.0}],
        )
        gen = BillingEntryGenerator()
        with pytest.raises(BillingEntryError):
            gen.generate(inv)

    def test_multi_compte_produit_aggregated(self, builder: InvoiceBuilder):
        inv = builder.manual(
            client_id="biat_bank",
            invoice_date=date(2026, 1, 1),
            line_items=[
                {"description": "Maintenance", "unit_price": 20000.0, "compte_produit": "7061"},
                {"description": "Développement", "unit_price": 10000.0, "compte_produit": "7062"},
            ],
        )
        gen   = BillingEntryGenerator()
        entry = gen.generate(inv)
        credit_comptes = [l.compte for l in entry.lines if l.credit is not None]
        assert "7061" in credit_comptes
        assert "7062" in credit_comptes
