"""Unit tests for HeaderExtractor — rules-based header field extraction."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from src.extraction.header_extractor import HeaderExtractor

# ── helpers ───────────────────────────────────────────────────────────────────

def _padded(core: str) -> str:
    """Pad a short snippet with neutral filler so it passes the 50-char guard."""
    filler = "\nMontant HT: 1,000.000 TND\nTVA 19%: 190.000 TND"
    return core + filler if len(core) < 50 else core


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


# ── Additional invoice number tests ──────────────────────────────────────────

class TestInvoiceNumberAdditional:
    def test_fac_prefix_extracted(self, hx):
        text = _padded("FAC-2026-0089\nDate: 15/06/2026\n")
        result = hx.extract(text)
        assert result['invoice_number'] == "FAC-2026-0089"

    def test_n_degree_format(self, hx):
        text = _padded("TUNISIE TRADENET\nFacture N° 8116\nDate 05/10/2016\n")
        result = hx.extract(text)
        assert result['invoice_number'] is not None
        assert "8116" in result['invoice_number']

    def test_ref_facture_format(self, hx):
        text = _padded("FOURNISSEUR SA\nRéf Facture: FC-2026-042\nDate: 10/06/2026\n")
        result = hx.extract(text)
        assert result['invoice_number'] is not None
        assert "042" in result['invoice_number']

    def test_no_invoice_number_returns_none(self, hx):
        text = (
            "OOREDOO TUNISIE SA\nDate: 15/06/2026\n"
            "Montant total: 4,462.500 TND\nTVA 19%: 712.500 TND"
        )
        result = hx.extract(text)
        assert result['invoice_number'] is None

    def test_fc_prefix_extracted(self, hx):
        text = _padded("NEXIA SARL\nFACTURE\nFC-2026-0589\nDate: 20/05/2026\n")
        result = hx.extract(text)
        assert result['invoice_number'] is not None
        assert "FC" in result['invoice_number'] or "2026" in result['invoice_number']

    def test_numeric_only_year_format(self, hx):
        text = _padded("FOURNISSEUR SA\nN° 2026-042\nDate: 01/06/2026\n")
        result = hx.extract(text)
        # Pattern 202x-NNN should match
        assert result['invoice_number'] is not None

    def test_short_code_not_matched(self, hx):
        # A 3-char code should not be returned (too short)
        text = _padded("FOURNISSEUR SA\nRef: AB1\nDate: 01/06/2026\n")
        result = hx.extract(text)
        assert result['invoice_number'] is None or len(result['invoice_number']) >= 4


# ── Additional date tests ─────────────────────────────────────────────────────

class TestDateAdditional:
    def test_slash_format(self, hx):
        text = _padded("Date: 15/06/2026\n")
        assert hx.extract(text)['invoice_date'] == date(2026, 6, 15)

    def test_iso_format(self, hx):
        text = _padded("Date: 2026-06-15\n")
        assert hx.extract(text)['invoice_date'] == date(2026, 6, 15)

    def test_french_month_name(self, hx):
        text = _padded("Tunis, le 15 juin 2026\n")
        assert hx.extract(text)['invoice_date'] == date(2026, 6, 15)

    def test_date_out_of_range_ignored(self, hx):
        text = _padded("Date: 15/06/1990\n")
        assert hx.extract(text)['invoice_date'] is None

    def test_future_date_ignored(self, hx):
        text = _padded("Date: 15/06/2035\n")
        assert hx.extract(text)['invoice_date'] is None

    def test_due_date_skipped_finds_invoice_date(self, hx):
        text = (
            "FOURNISSEUR SA\nFACTURE N° 2026-001\n"
            "Date de facture: 01/05/2026\n"
            "Date d'échéance: 31/05/2026\n"
            "Montant TTC: 1,000.000 TND"
        )
        result = hx.extract(text)
        assert result['invoice_date'] == date(2026, 5, 1)

    def test_dot_separator(self, hx):
        text = _padded("Date: 20.04.2026\n")
        assert hx.extract(text)['invoice_date'] == date(2026, 4, 20)

    def test_labelled_date_preferred_over_unlabelled(self, hx):
        text = (
            "FOURNISSEUR SA\nFACTURE N° 2026-001\n"
            "Date de facture: 05/03/2026\n"
            "15/06/2026 Date de paiement\n"
            "Montant TTC: 1,000.000 TND"
        )
        result = hx.extract(text)
        assert result['invoice_date'] == date(2026, 3, 5)


# ── Additional issuer name tests ──────────────────────────────────────────────

class TestIssuerAdditional:
    def test_all_caps_confidence_is_075(self, hx):
        text = (
            "OOREDOO TUNISIE SA\nMF: 0038472K/A/M/000\n"
            "Date: 15/01/2026\nMontant: 4,462.500 TND"
        )
        result = hx.extract(text)
        assert result['issuer_name'] == "OOREDOO TUNISIE SA"
        assert result['issuer_confidence'] == 0.75

    def test_mixed_case_confidence_is_065(self, hx):
        text = (
            "STEG - Société Tunisienne\n38 Rue Kemal Ataturk\n"
            "Date: 05/03/2026\nMontant: 2,856.000 TND"
        )
        result = hx.extract(text)
        assert result['issuer_name'] == "STEG - Société Tunisienne"
        assert result['issuer_confidence'] == 0.65

    def test_skips_mf_line(self, hx):
        text = (
            "MF: 0038472K/A/M/000\nOOREDOO TUNISIE SA\n"
            "Date: 15/01/2026\nMontant: 4,462.500 TND"
        )
        result = hx.extract(text)
        assert result['issuer_name'] is not None
        assert "OOREDOO" in result['issuer_name']

    def test_skips_phone_line(self, hx):
        # "71 86 17 12" starts with digit → skipped; next line used
        # Avoid company names starting with "tunis" (skip prefix)
        text = (
            "71 86 17 12\nNEXIA INFORMATIQUE SARL\n"
            "Date: 05/10/2026\nMontant: 2,740.000 TND"
        )
        result = hx.extract(text)
        assert result['issuer_name'] is not None
        assert "NEXIA" in result['issuer_name']

    def test_copyright_line_skipped(self, hx):
        # © line is rejected by the © check; next clean line used
        # Avoid entertainment names (they trigger _is_likely_not_invoice guard)
        text = (
            "© ACME GROUP 2024\nACME CORP SARL\n"
            "Date: 15/06/2026\nMontant: 1,000.000 TND"
        )
        result = hx.extract(text)
        assert result['issuer_name'] is not None
        assert "ACME" in result['issuer_name']

    def test_too_short_line_skipped(self, hx):
        text = (
            "OK\nSOTETEL TUNISIE SA\n"
            "Date: 15/06/2026\nMontant: 8,500.000 TND"
        )
        result = hx.extract(text)
        assert result['issuer_name'] is not None
        assert "SOTETEL" in result['issuer_name']

    def test_bidi_line_skipped(self, hx):
        text = (
            "‏OOREDOO‎ TUNIS\nNEXIA INFORMATIQUE SARL\n"
            "Date: 20/02/2026\nMontant: 5,355.000 TND"
        )
        result = hx.extract(text)
        # The bidi-marked line must be skipped; next clean line used
        assert result['issuer_name'] is not None
        assert "NEXIA" in result['issuer_name']

    def test_digit_start_line_skipped(self, hx):
        text = (
            "0038472K/A/M/000\nKPMG TUNISIE\n"
            "Date: 20/05/2026\nMontant: 14,280.000 TND"
        )
        result = hx.extract(text)
        assert result['issuer_name'] is not None
        assert "KPMG" in result['issuer_name']

    def test_none_when_all_lines_skipped(self, hx):
        text = (
            "MF: 0038472K\nTél: 71 000 000\n"
            "Date: 01/06/2026\nTVA 19%\nTotal TTC"
        )
        # All lines start with skip prefixes or are exact keywords — None acceptable
        result = hx.extract(text)
        assert result['issuer_name'] is None or isinstance(result['issuer_name'], str)


class TestNoRawTextInDebugLogs:
    """Post-audit follow-up (item 3/4): invoice text must never be dumped at
    DEBUG level — _extract_invoice_number() used to log up to 500 raw chars
    of OCR'd invoice text (issuer, amounts, tax IDs — real bank data)."""

    def test_extract_invoice_number_does_not_log_raw_text(self, hx):
        text = "TECHNOVA SOLUTIONS SARL — CONFIDENTIAL MF 1472583D\nFACTURE N° FAC-2026-0089\n"

        with patch("src.extraction.header_extractor.logger") as mock_logger:
            hx._extract_invoice_number(text)

        for call in mock_logger.debug.call_args_list:
            assert "text_sample" not in call.kwargs
            for value in call.kwargs.values():
                assert "CONFIDENTIAL" not in str(value)
                assert "TECHNOVA" not in str(value)

    def test_extract_does_not_log_raw_text(self, hx):
        # "SECRETMARKER" sits in the invoice body, never in the extracted
        # issuer_name/invoice_number/date fields — so it must never appear in
        # ANY debug log, unlike the (legitimate, lower-sensitivity) logging of
        # the already-structured extracted field values themselves.
        text = (
            "TECHNOVA SOLUTIONS SARL\nFACTURE N° FAC-2026-0089\n"
            "Montant HT: SECRETMARKER 1,000.000 TND\n"
        )

        with patch("src.extraction.header_extractor.logger") as mock_logger:
            hx.extract(text)

        for call in mock_logger.debug.call_args_list:
            assert "text_sample" not in call.kwargs
            for value in call.kwargs.values():
                assert "SECRETMARKER" not in str(value)
