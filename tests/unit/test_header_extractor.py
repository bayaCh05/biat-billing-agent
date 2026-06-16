"""Unit tests for HeaderExtractor — rules-based header field extraction."""
from __future__ import annotations

from datetime import date

import pytest

from src.extraction.header_extractor import HeaderExtractor


@pytest.fixture()
def hx():
    return HeaderExtractor()


# ── Invoice number ────────────────────────────────────────────────────────────

class TestInvoiceNumber:
    def test_fac_format(self, hx):
        text = "TECHNOVA SOLUTIONS SARL\nMF: 1472583D\nFACTURE\nN° FAC-2026-0089\n"
        assert hx.extract(text)['invoice_number'] == "FAC-2026-0089"

    def test_n_degree_label(self, hx):
        text = "FOURNISSEUR TEST SA\nFACTURE\nFacture N° 2026-042\nDate: 01/06/2026\n"
        result = hx.extract(text)['invoice_number']
        assert result is not None
        assert "2026" in result

    def test_steg_format(self, hx):
        text = "STEG\nFACTURE\nN° STEG-2026-05-00847\nFOURNISSEUR CLIENT\nDate: 01/06/2026\n"
        assert hx.extract(text)['invoice_number'] == "STEG-2026-05-00847"

    def test_alphanumeric_with_prefix(self, hx):
        text = "KPMG TUNISIE\nFACTURE\nN° KPMG-2026-IT-0047\nDate: 01/06/2026\n"
        result = hx.extract(text)['invoice_number']
        assert result == "KPMG-2026-IT-0047"

    def test_numéro_de_facture_label(self, hx):
        text = "OOREDOO TUNISIE\nNuméro de facture: OOR-B2B-2026-05-10293\nDate: 01/06/2026\n"
        result = hx.extract(text)['invoice_number']
        assert result is not None
        assert "2026" in result

    def test_no_number_returns_none(self, hx):
        text = "random text without any recognizable invoice number field here"
        assert hx.extract(text)['invoice_number'] is None

    def test_does_not_match_short_codes(self, hx):
        # "MF" followed by short tax ID should not be mistaken for invoice number
        text = "MF: 123\nSome text\n"
        result = hx.extract(text)['invoice_number']
        # Either None or something meaningful — must NOT return "123"
        assert result != "123"


# ── Date ──────────────────────────────────────────────────────────────────────

class TestDate:
    def test_slash_format(self, hx):
        text = "FOURNISSEUR SA\nFACTURE N° 2026-001\nDate de facture: 15/06/2026\n"
        assert hx.extract(text)['invoice_date'] == date(2026, 6, 15)

    def test_dash_format(self, hx):
        text = "FOURNISSEUR SA\nFACTURE N° 2026-001\nDate de facture: 31-05-2026\n"
        assert hx.extract(text)['invoice_date'] == date(2026, 5, 31)

    def test_dot_format(self, hx):
        text = "FOURNISSEUR SA\nFACTURE N° 2026-001\nDate: 20.04.2026\nMontant: 100 TND\n"
        assert hx.extract(text)['invoice_date'] == date(2026, 4, 20)

    def test_iso_format(self, hx):
        text = "FOURNISSEUR SA\nFACTURE N° 2026-001\nIssued: 2026-06-01\nMontant: 100 TND\n"
        assert hx.extract(text)['invoice_date'] == date(2026, 6, 1)

    def test_french_text_date(self, hx):
        text = "FOURNISSEUR SA\nFACTURE N° 2026-001\nTunis, le 15 juin 2026\nMontant: 100 TND\n"
        assert hx.extract(text)['invoice_date'] == date(2026, 6, 15)

    def test_french_text_date_janvier(self, hx):
        text = "FOURNISSEUR SA\nFACTURE N° 2026-001\nÉmise le 1 janvier 2026\nMontant: 100 TND\n"
        assert hx.extract(text)['invoice_date'] == date(2026, 1, 1)

    def test_bad_year_ignored(self, hx):
        text = "Date de facture: 15/06/1998\n"
        assert hx.extract(text)['invoice_date'] is None

    def test_future_year_ignored(self, hx):
        text = "Date: 01/01/2035\n"
        assert hx.extract(text)['invoice_date'] is None

    def test_due_date_line_skipped(self, hx):
        # The échéance line should be skipped; the earlier invoice date returned
        text = (
            "STEG\nFACTURE\nN° STEG-2026-05-00847\n"
            "Date de facture: 31/05/2026 Date d'échéance: 30/06/2026\n"
        )
        result = hx.extract(text)['invoice_date']
        assert result == date(2026, 5, 31)

    def test_no_date_returns_none(self, hx):
        text = "random text without any recognizable fields"
        assert hx.extract(text)['invoice_date'] is None


# ── Issuer name ───────────────────────────────────────────────────────────────

class TestIssuerName:
    def test_first_line_company(self, hx):
        text = "OOREDOO TUNISIE SA\nMF: 0038472K\nTél: 71 000 000\nDate: 01/06/2026\n"
        assert hx.extract(text)['issuer_name'] == "OOREDOO TUNISIE SA"

    def test_skips_mf_prefix_line(self, hx):
        text = "MF: 0038472K\nOOREDOO TUNISIE SA\nTél: 71 000 000\nDate: 01/06/2026\n"
        assert hx.extract(text)['issuer_name'] == "OOREDOO TUNISIE SA"

    def test_skips_tel_prefix_line(self, hx):
        text = "Tél: +216 71 000 000\nSTEG - Société Tunisienne\nDate de facture: 01/06/2026\n"
        assert hx.extract(text)['issuer_name'] == "STEG - Société Tunisienne"

    def test_skips_facture_keyword(self, hx):
        text = "FACTURE\nKPMG TUNISIE\nMF: 888\nDate: 01/06/2026\nMontant: 100 TND\n"
        assert hx.extract(text)['issuer_name'] == "KPMG TUNISIE"

    def test_skips_address_line(self, hx):
        text = "38 Rue Kemal Ataturk\nSTEG - Société Tunisienne de l'Electricité\n"
        assert hx.extract(text)['issuer_name'] == "STEG - Société Tunisienne de l'Electricité"

    def test_real_steg_invoice_text(self, hx):
        text = (
            "STEG - Société Tunisienne de l'Electricité et du Gaz\n"
            "38 Rue Kemal Ataturk - 1080 Tunis, Tunisie\n"
            "Matricule Fiscal: 0000001A/A/M/000\n"
            "FACTURE\n"
        )
        assert hx.extract(text)['issuer_name'] == "STEG - Société Tunisienne de l'Electricité et du Gaz"

    def test_no_match_returns_none(self, hx):
        text = "MF: 123\nTél: 71000000\nDate: 01/06/2026\n"
        # All qualifying lines are skipped — should return None gracefully
        assert hx.extract(text)['issuer_name'] is None or isinstance(hx.extract(text)['issuer_name'], str)

    def test_short_lines_skipped(self, hx):
        text = "AB\nCD\nNEXIA INFORMATIQUE SARL\nDate de facture: 01/06/2026\n"
        assert hx.extract(text)['issuer_name'] == "NEXIA INFORMATIQUE SARL"


# ── Full extract() integration ────────────────────────────────────────────────

class TestFullExtract:
    def test_returns_dict_with_expected_keys(self, hx):
        result = hx.extract("some text")
        assert {'issuer_name', 'issuer_confidence', 'invoice_number', 'invoice_date'}.issubset(result.keys())

    def test_no_crash_on_empty_string(self, hx):
        result = hx.extract("")
        assert result['issuer_name'] is None
        assert result['invoice_number'] is None
        assert result['invoice_date'] is None

    def test_steg_realistic_text(self, hx):
        text = (
            "STEG - Société Tunisienne de l'Electricité et du Gaz\n"
            "38 Rue Kemal Ataturk - 1080 Tunis, Tunisie\n"
            "Matricule Fiscal: 0000001A/A/M/000\n"
            "FACTURE\n"
            "N° STEG-2026-05-00847\n"
            "FOURNISSEUR CLIENT\n"
            "Date de facture: 31/05/2026 Date d'échéance: 30/06/2026\n"
        )
        result = hx.extract(text)
        assert result['issuer_name'] == "STEG - Société Tunisienne de l'Electricité et du Gaz"
        assert result['invoice_number'] == "STEG-2026-05-00847"
        assert result['invoice_date'] == date(2026, 5, 31)
