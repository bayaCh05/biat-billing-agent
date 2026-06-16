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


# ── Additional real invoice formats that must PASS ───────────────────────────

class TestRealInvoiceFormats:
    def test_ttn_invoice_passes(self):
        text = """\
Tunisie TradeNet
Facture N 8116  Date 05/10/2016
Matricule Fiscal : 41101180
T.V.A.%  12   P.U.H.T.V.A.  2,000
Total H.T.V.A.  2,000
Montant T.T.C  2,740
Droit de Timbre  0,500"""
        assert _v.validate(text) is None

    def test_steg_invoice_passes(self):
        text = (
            "STEG - Societe Tunisienne de l'Electricite et du Gaz\n"
            "Facture N° 2026-0847\nDate de facture: 05/03/2026\n"
            "Montant TTC: 2,285.000 TND\nTVA 19%: 364.500 TND"
        )
        assert _v.validate(text) is None

    def test_kpmg_invoice_passes(self):
        text = (
            "KPMG TUNISIE\nMF: 0098765J/A/M/000\n"
            "Honoraires d'audit et conseil\n"
            "Montant HT: 12,000.000 TND\nTVA 19%: 2,280.000 TND\n"
            "Total TTC: 14,280.000 TND"
        )
        assert _v.validate(text) is None

    def test_arabic_french_bilingual_passes(self):
        text = (
            "STAR ASSURANCES SA   MF: 0123456A/P/M/000\n"
            "فاتورة رقم: FAC-2026-STAR-0089\n"
            "Date de facture: 01/06/2026\n"
            "Montant HT: 1,200.000 TND\n"
            "TVA 19%:    228.000 TND\n"
            "Total TTC: 1,428.000 TND"
        )
        assert _v.validate(text) is None

    def test_very_short_real_invoice_passes(self):
        # Exactly at/above _MIN_CHARS with strong signals
        text = "Facture NEXIA INFORMATIQUE\nTVA 19%\nTotal TTC: 500.000 TND"
        assert _v.validate(text) is None

    def test_formation_exempt_tva_passes(self):
        text = (
            "CIEL FORMATION SARL\nMF: 1398741G/A/M/000\n"
            "Facture N° FAC-2026-07-CIEL\n"
            "Formation Cybersécurité ISO 27001 — 3 jours\n"
            "Montant HT: 4,200.000 TND\nTVA: 0% (exonéré)\n"
            "Total TTC: 4,200.000 TND"
        )
        assert _v.validate(text) is None


# ── Non-invoice files that must FAIL ─────────────────────────────────────────

class TestNonInvoiceRejected:
    def test_login_page_rejected(self):
        text = (
            "Forgot your password? Click here to reset.\n"
            "Sign In to your account\nUsername:\nPassword:\n"
            "Remember me on this device. New user? Register here."
        )
        with pytest.raises(NotAnInvoiceError):
            _v.validate(text)

    def test_bank_statement_rejected(self):
        text = (
            "Relevé de Compte Mensuel\n"
            "BIAT - Banque Internationale Arabe de Tunisie\n"
            "Compte N° 001-123456-78\n"
            "SOLDE INITIAL    12,450.00\n"
            "REGLEMENT CHEQUE  1,200.00\n"
            "ENCAISSEMENT VIR  3,500.00\n"
            "SOLDE FINAL      14,750.00"
        )
        with pytest.raises(NotAnInvoiceError):
            _v.validate(text)

    def test_cv_rejected(self):
        text = (
            "Curriculum Vitae — Jean Dupont\n"
            "Experience: 5 years software development\n"
            "Skills: Python, SQL, REST APIs\n"
            "Education: Master Computer Science 2019\n"
            "References available on request."
        )
        with pytest.raises(NotAnInvoiceError):
            _v.validate(text)

    def test_empty_string_rejected(self):
        with pytest.raises(NotAnInvoiceError) as exc:
            _v.validate("")
        assert exc.value.reason == "text_too_short"

    def test_only_numbers_rejected(self):
        with pytest.raises(NotAnInvoiceError):
            _v.validate("123 456 789 000 111 222 333 444 555")

    def test_presentation_rejected(self):
        text = (
            "Présentation du projet infrastructure cloud\n"
            "Objectifs stratégiques 2026\n"
            "Slide 1: Introduction\nSlide 2: Architecture cible\n"
            "Slide 3: Planning et jalons\nSlide 4: Budget prévisionnel"
        )
        with pytest.raises(NotAnInvoiceError):
            _v.validate(text)


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_score_exactly_at_threshold_passes(self):
        # facture (3 pts) — exactly at _MIN_SCORE=3, with 1 number
        text = "Facture\nMontant: 1,000.000 TND\nDépenses administratives 2026"
        assert _v.validate(text) is None

    def test_reject_immediately_takes_priority_over_invoice_keywords(self):
        # Has invoice keywords but also Bridgerton — must be rejected
        text = (
            "Facture TVA TND Montant HT Total TTC Fournisseur\n"
            "Bridgerton Season 4 Episode 2 Netflix\n"
            "1,000.000 TND"
        )
        with pytest.raises(NotAnInvoiceError) as exc:
            _v.validate(text)
        assert "non_invoice_content" in exc.value.reason

    def test_whitespace_only_rejected(self):
        with pytest.raises(NotAnInvoiceError) as exc:
            _v.validate("   \n\n   \t   ")
        assert exc.value.reason == "text_too_short"

    def test_reason_encodes_threshold(self):
        """Rejection reason always encodes the required threshold."""
        text = "This document is about project planning for Q3 2026 deliverables."
        with pytest.raises(NotAnInvoiceError) as exc:
            _v.validate(text)
        assert "_of_3" in exc.value.reason

    def test_not_an_invoice_error_is_value_error(self):
        with pytest.raises(ValueError):
            _v.validate("")

    def test_ollama_url_not_needed_for_validation(self):
        # InvoiceValidator has no LLM dependency — must work offline
        v2 = InvoiceValidator()
        with pytest.raises(NotAnInvoiceError):
            v2.validate("not an invoice")

    def test_filename_kwarg_does_not_affect_result(self):
        _v.validate(REAL_INVOICE, filename="test.pdf")  # must not raise
        with pytest.raises(NotAnInvoiceError):
            _v.validate("hello", filename="short.pdf")


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
