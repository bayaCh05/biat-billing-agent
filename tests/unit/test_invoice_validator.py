"""Unit tests for InvoiceValidator."""
from __future__ import annotations

import pytest

from src.extraction.invoice_validator import InvoiceValidator, NotAnInvoiceError

_v = InvoiceValidator()

# ── Fixtures ──────────────────────────────────────────────────────────────────

REAL_INVOICE = """\
FACTURE N° FAC-2026-089
OOREDOO TUNISIE SA - MF: 0038472K
Date de facture: 15/06/2026
Montant HT: 2,420.000 TND
TVA 19%:      459.800 TND
Total TTC:  2,879.800 TND"""

ARABIC_INVOICE = """\
STAR ASSURANCES SA   MF: 0123456A/P/M/000
فاتورة رقم: FAC-2026-STAR-0089
Date de facture: 01/06/2026
Montant HT: 1,200.000 TND
TVA 19%:    228.000 TND
Total TTC: 1,428.000 TND
المجموع الإجمالي شامل للضريبة"""

PROJECT_REPORT = (
    "This is a comprehensive project report about infrastructure development "
    "and planning methodology for the upcoming fiscal quarter initiatives."
)


# ── Passing cases ─────────────────────────────────────────────────────────────

class TestValidPasses:
    def test_real_invoice_passes(self):
        _v.validate(REAL_INVOICE)  # must not raise

    def test_arabic_invoice_passes(self):
        # Bilingual Arabic/French invoice with TND amounts and TVA
        _v.validate(ARABIC_INVOICE)

    def test_steg_invoice_passes(self):
        text = (
            "STEG - Societe Tunisienne de l'Electricite et du Gaz\n"
            "FACTURE\nNumero: FAC-2026-03-STEG\n"
            "Date de facture: 05/03/2026\n"
            "Montant HT: 8,400.000 TND\nTVA 19%: 1,596.000 TND\n"
            "Total TTC: 9,996.000 TND"
        )
        _v.validate(text)

    def test_ttn_invoice_passes(self):
        text = """\
Tunisie TradeNet
Facture N 8116  Date 05/10/2016
Matricule Fiscal : 41101180
T.V.A.%  12   P.U.H.T.V.A.  2,000
Total H.T.V.A.  2,000
Montant T.T.C  2,740
Droit de Timbre  0,500"""
        _v.validate(text)  # must not raise

    def test_filename_kwarg_accepted(self):
        _v.validate(REAL_INVOICE, filename="facture_test.pdf")


# ── Immediate-reject cases ────────────────────────────────────────────────────

class TestImmediateReject:
    def test_bridgerton_rejected(self):
        text = "© Netflix Bridgerton Season 4 Episode 2 — full script"
        with pytest.raises(NotAnInvoiceError) as exc:
            _v.validate(text)
        assert "non_invoice_content" in exc.value.reason

    def test_netflix_rejected(self):
        with pytest.raises(NotAnInvoiceError) as exc:
            _v.validate("Netflix Original Series — all rights reserved entertainment streaming")
        assert "non_invoice_content" in exc.value.reason

    def test_screenplay_rejected(self):
        with pytest.raises(NotAnInvoiceError) as exc:
            _v.validate("screenplay by John Doe, directed by Jane Smith — production draft 2026")
        assert "non_invoice_content" in exc.value.reason

    def test_cv_rejected(self):
        with pytest.raises(NotAnInvoiceError) as exc:
            _v.validate("Curriculum Vitae — John Doe — Software Engineer with 10 years experience")
        assert "non_invoice_content" in exc.value.reason

    def test_episode_rejected(self):
        with pytest.raises(NotAnInvoiceError) as exc:
            _v.validate("Disney+ Original — Episode 3 Season 2 — special extended version now streaming")
        assert "non_invoice_content" in exc.value.reason


# ── Length-check cases ────────────────────────────────────────────────────────

class TestTooShort:
    def test_empty_string_rejected(self):
        with pytest.raises(NotAnInvoiceError) as exc:
            _v.validate("")
        assert exc.value.reason == "text_too_short"

    def test_hello_rejected(self):
        with pytest.raises(NotAnInvoiceError) as exc:
            _v.validate("hello")
        assert exc.value.reason == "text_too_short"

    def test_whitespace_only_rejected(self):
        with pytest.raises(NotAnInvoiceError) as exc:
            _v.validate("   \n\n   ")
        assert exc.value.reason == "text_too_short"


# ── Score-threshold cases ─────────────────────────────────────────────────────

class TestLowScore:
    def test_project_report_rejected(self):
        with pytest.raises(NotAnInvoiceError) as exc:
            _v.validate(PROJECT_REPORT)
        assert "low_invoice_score" in exc.value.reason

    def test_score_detail_in_reason(self):
        with pytest.raises(NotAnInvoiceError) as exc:
            _v.validate(PROJECT_REPORT)
        # Reason encodes both actual and required score
        assert "_of_3" in exc.value.reason

    def test_random_prose_rejected(self):
        text = (
            "The meeting was held on Monday to discuss the upcoming roadmap. "
            "Several team members raised concerns about the timeline and scope "
            "of deliverables for the next release cycle planned for autumn."
        )
        with pytest.raises(NotAnInvoiceError) as exc:
            _v.validate(text)
        assert "low_invoice_score" in exc.value.reason or \
               "insufficient_numeric_values" in exc.value.reason


# ── Signal scoring (edge cases near threshold) ────────────────────────────────

class TestSignalScoring:
    def test_partial_signals_below_threshold(self):
        # Only 1 weak signal ("description") — score=1, below threshold=5
        text = (
            "Description of the project activities undertaken during the quarter "
            "including all deliverables and milestones achieved by the team members."
        )
        with pytest.raises(NotAnInvoiceError) as exc:
            _v.validate(text)
        assert "low_invoice_score" in exc.value.reason

    def test_tva_and_total_enough(self):
        # TVA (3) + total ttc (3) + TND (2) + numeric amounts = score >= 5
        text = (
            "TVA 19% applicable\n"
            "Total TTC: 1,000.000 TND\n"
            "Montant restant dû: 850.000 TND\n"
            "Veuillez régler dans les 30 jours suivant la date de réception."
        )
        _v.validate(text)  # must not raise


# ── NotAnInvoiceError attributes ─────────────────────────────────────────────

class TestErrorAttributes:
    def test_reason_attribute_set(self):
        with pytest.raises(NotAnInvoiceError) as exc:
            _v.validate("hello")
        assert exc.value.reason == "text_too_short"

    def test_text_sample_attribute_set(self):
        with pytest.raises(NotAnInvoiceError) as exc:
            _v.validate(PROJECT_REPORT)
        assert isinstance(exc.value.text_sample, str)

    def test_str_representation(self):
        err = NotAnInvoiceError(reason="test_reason", text_sample="sample")
        assert "Not an invoice" in str(err)
        assert "test_reason" in str(err)
