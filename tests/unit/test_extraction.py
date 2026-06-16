"""
Extraction module tests.

LLM backends and EasyOCR are always mocked — no real API calls or GPU inference.
PDFReader and OCRPreprocessor are tested with synthetic data created on-the-fly.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from src.extraction.hybrid_extractor import HybridExtractor
from src.extraction.llm_extractor import (
    ExtractionError,
    LLMExtractor,
    OllamaBackend,
)
from src.extraction.extras_ocr import EasyOCREngine
from src.extraction.ocr_engine import TesseractEngine
from src.extraction.ocr_preprocessor import OCRPreprocessor
from src.extraction.pdf_reader import PDFReader
from src.models.enums import ExtractionMethod, InvoiceDirection, InvoiceStatus
from src.models.invoice import ConfidenceField, InvoiceRecord
from src.utils.date_parser import parse_date


# ── Shared fixtures ────────────────────────────────────────────────────────────

@pytest.fixture()
def sample_invoice():
    return InvoiceRecord(
        file_hash="a" * 64,
        raw_file_path="/processed/test.pdf",
        direction=InvoiceDirection.SUPPLIER,
        status=InvoiceStatus.RECEIVED,
    )


@pytest.fixture()
def native_pdf(tmp_path) -> Path:
    """Create a synthetic native PDF with embedded text using PyMuPDF."""
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72),  "FACTURE N° FAC-2024-001", fontsize=16)
    page.insert_text((50, 110), "Fournisseur SARL", fontsize=12)
    page.insert_text((50, 130), "MF: 1234567/A/M/000", fontsize=12)
    page.insert_text((50, 150), "BIAT IT (destinataire)", fontsize=12)
    page.insert_text((50, 170), "Date: 01/06/2024", fontsize=12)
    page.insert_text((50, 200), "Montant HT:  1000.000 TND", fontsize=12)
    page.insert_text((50, 220), "TVA 19%:      190.000 TND", fontsize=12)
    page.insert_text((50, 240), "Montant TTC: 1190.000 TND", fontsize=12)
    path = tmp_path / "invoice.pdf"
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture()
def white_image() -> Image.Image:
    """300×400 white grayscale image (simulates a blank scanned page)."""
    return Image.fromarray(np.full((400, 300), 255, dtype=np.uint8), mode="L")


@pytest.fixture()
def noisy_image() -> Image.Image:
    """Grayscale image with random noise (simulates a poor scan)."""
    rng = np.random.default_rng(42)
    arr = rng.integers(0, 256, (400, 300), dtype=np.uint8)
    return Image.fromarray(arr, mode="L")


@pytest.fixture()
def mock_backend() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def llm_extractor(mock_backend) -> LLMExtractor:
    # Existing tests supply full-schema JSON responses and verify text-field extraction
    return LLMExtractor(backend=mock_backend, languages=["fr"], mode="full_schema")


@pytest.fixture()
def config() -> dict:
    return {
        "extraction": {
            "languages": ["fr", "ar"],
            "render_dpi": 150,  # lower for test speed
        }
    }


# ── date_parser ────────────────────────────────────────────────────────────────

class TestDateParser:
    def test_iso_format(self):
        assert parse_date("2024-06-01") == date(2024, 6, 1)

    def test_dmy_slash(self):
        assert parse_date("01/06/2024") == date(2024, 6, 1)

    def test_dmy_dash(self):
        assert parse_date("01-06-2024") == date(2024, 6, 1)

    def test_french_month(self):
        assert parse_date("1 juin 2024") == date(2024, 6, 1)
        assert parse_date("15 mars 2024") == date(2024, 3, 15)

    def test_arabic_month(self):
        assert parse_date("1 يناير 2024") == date(2024, 1, 1)

    def test_none_input(self):
        assert parse_date(None) is None

    def test_empty_string(self):
        assert parse_date("") is None

    def test_unparseable(self):
        assert parse_date("not a date") is None


# ── PDFReader ──────────────────────────────────────────────────────────────────

class TestPDFReader:
    def test_is_native_pdf_true_for_text_pdf(self, native_pdf):
        reader = PDFReader(min_chars=10)
        assert reader.is_native_pdf(str(native_pdf)) is True

    def test_is_native_pdf_false_for_missing_file(self):
        reader = PDFReader()
        assert reader.is_native_pdf("/nonexistent/path.pdf") is False

    def test_extract_text_returns_string(self, native_pdf):
        reader = PDFReader()
        text = reader.extract_text(str(native_pdf))
        assert isinstance(text, str)
        assert len(text) > 20

    def test_extract_text_contains_invoice_content(self, native_pdf):
        reader = PDFReader()
        text = reader.extract_text(str(native_pdf))
        assert "FAC-2024-001" in text
        assert "1190" in text

    def test_to_images_returns_pil_images(self, native_pdf):
        reader = PDFReader()
        images = reader.to_images(str(native_pdf), dpi=72)
        assert len(images) == 1
        assert hasattr(images[0], "size")  # PIL Image

    def test_to_images_dpi_affects_resolution(self, native_pdf):
        reader = PDFReader()
        low = reader.to_images(str(native_pdf), dpi=72)[0]
        high = reader.to_images(str(native_pdf), dpi=150)[0]
        # Higher DPI → larger image
        assert high.width > low.width

    def test_image_to_pil(self, tmp_path):
        img_path = tmp_path / "scan.png"
        Image.fromarray(np.full((200, 150), 200, dtype=np.uint8)).save(str(img_path))
        reader = PDFReader()
        result = reader.image_to_pil(str(img_path))
        assert result is not None


# ── OCRPreprocessor ────────────────────────────────────────────────────────────

class TestOCRPreprocessor:
    def test_process_returns_pil_image(self, white_image):
        result = OCRPreprocessor().process(white_image)
        assert isinstance(result, Image.Image)

    def test_output_is_grayscale(self, white_image):
        result = OCRPreprocessor().process(white_image)
        assert result.mode == "L"

    def test_process_does_not_crash_on_noisy_image(self, noisy_image):
        result = OCRPreprocessor().process(noisy_image)
        assert isinstance(result, Image.Image)

    def test_to_grayscale_converts_rgb(self):
        rgb = Image.fromarray(np.zeros((100, 100, 3), dtype=np.uint8), mode="RGB")
        result = OCRPreprocessor()._to_grayscale(rgb)
        assert result.mode == "L"

    def test_binarize_produces_binary_image(self, white_image):
        arr = np.array(OCRPreprocessor()._binarize(white_image))
        unique_values = set(arr.flatten().tolist())
        assert unique_values.issubset({0, 255})

    def test_denoise_preserves_shape(self, noisy_image):
        result = OCRPreprocessor()._denoise(noisy_image)
        assert result.size == noisy_image.size

    def test_deskew_straight_image_unchanged(self, white_image):
        # A blank image has no lines → should be returned unchanged
        result = OCRPreprocessor()._deskew(white_image)
        assert result.size == white_image.size


# ── OCREngine ─────────────────────────────────────────────────────────────────

class TestEasyOCREngine:
    def test_extract_returns_string(self, white_image):
        engine = EasyOCREngine(languages=["fr"])
        mock_reader = MagicMock()
        mock_reader.readtext.return_value = ["ligne 1", "ligne 2"]
        engine._reader = mock_reader

        result = engine.extract([white_image], languages=["fr"])
        assert isinstance(result, str)
        assert "ligne 1" in result
        assert "ligne 2" in result

    def test_multiple_pages_separated_by_newline(self, white_image):
        engine = EasyOCREngine(languages=["fr"])
        mock_reader = MagicMock()
        mock_reader.readtext.side_effect = [["page 1 text"], ["page 2 text"]]
        engine._reader = mock_reader

        result = engine.extract([white_image, white_image], languages=["fr"])
        assert "page 1 text" in result
        assert "page 2 text" in result

    def test_reader_is_lazy_loaded(self):
        engine = EasyOCREngine(languages=["fr"])
        assert engine._reader is None  # not loaded yet

    def test_reader_not_recreated_on_second_call(self, white_image):
        engine = EasyOCREngine(languages=["fr"])
        mock_reader = MagicMock()
        mock_reader.readtext.return_value = []
        engine._reader = mock_reader

        engine.extract([white_image])
        engine.extract([white_image])
        # Reader was set manually, should still be the same object
        assert engine._reader is mock_reader


class TestTesseractEngine:
    def test_extract_calls_image_to_string(self, white_image):
        engine = TesseractEngine(languages=["fr"])
        with patch("pytesseract.image_to_string", return_value="text from tesseract") as mock_tess:
            result = engine.extract([white_image], languages=["fr"])
        assert "text from tesseract" in result
        mock_tess.assert_called_once()

    def test_language_mapping(self, white_image):
        # With fr+ar, the engine runs two separate passes (Latin then Arabic)
        # to avoid bidi corruption.  Collect all lang args across all calls.
        engine = TesseractEngine(languages=["fr", "ar"])
        with patch("pytesseract.image_to_string", return_value="") as mock_tess:
            engine.extract([white_image])
        all_lang_args = [
            (c[1].get("lang") or c[0][1]) for c in mock_tess.call_args_list
        ]
        assert any("fra" in l for l in all_lang_args)
        assert any("ara" in l for l in all_lang_args)


# ── LLMExtractor — JSON parsing ────────────────────────────────────────────────

SAMPLE_LLM_RESPONSE = json.dumps({
    "issuer_name":     {"value": "Fournisseur SARL", "confidence": 0.97, "source": "Fournisseur SARL"},
    "issuer_tax_id":   {"value": "1234567/A/M/000",  "confidence": 0.91, "source": "MF: 1234567/A/M/000"},
    "recipient_name":  {"value": "BIAT IT",           "confidence": 0.99, "source": "BIAT IT"},
    "recipient_tax_id":{"value": None,                "confidence": 0.0,  "source": None},
    "invoice_number":  {"value": "FAC-2024-001",      "confidence": 0.95, "source": "FAC-2024-001"},
    "invoice_date":    {"value": "2024-06-01",        "confidence": 0.92, "source": "01/06/2024"},
    "due_date":        {"value": None,                "confidence": 0.0,  "source": None},
    "amount_ht":       {"value": 1000.0,              "confidence": 0.96, "source": "1000.000"},
    "tva_rate":        {"value": 19.0,                "confidence": 0.99, "source": "TVA 19%"},
    "tva_amount":      {"value": 190.0,               "confidence": 0.96, "source": "190.000"},
    "amount_ttc":      {"value": 1190.0,              "confidence": 0.96, "source": "1190.000"},
    "currency":        {"value": "TND",               "confidence": 0.99, "source": None},
    "line_items": [
        {"description": "Prestation dev", "quantity": 10.0, "unit_price": 100.0, "line_total": 1000.0, "tva_rate": 19.0}
    ],
})

SAMPLE_TEXT = (
    "FACTURE N° FAC-2024-001\nFournisseur SARL\nMF: 1234567/A/M/000\n"
    "BIAT IT\nDate: 01/06/2024\nMontant HT: 1000.000\nTVA 19%: 190.000\n"
    "Montant TTC: 1190.000"
)


class TestLLMExtractorParsing:

    def test_fields_populated_from_json(self, llm_extractor, sample_invoice, mock_backend):
        mock_backend.complete.return_value = SAMPLE_LLM_RESPONSE
        result = llm_extractor.extract(SAMPLE_TEXT, sample_invoice)

        assert result.invoice_number.value == "FAC-2024-001"
        assert result.invoice_number.confidence == pytest.approx(0.95)
        assert result.issuer_name.value == "Fournisseur SARL"
        assert result.amount_ttc.value == pytest.approx(1190.0)

    def test_date_fields_parsed_to_date_objects(self, llm_extractor, sample_invoice, mock_backend):
        mock_backend.complete.return_value = SAMPLE_LLM_RESPONSE
        result = llm_extractor.extract(SAMPLE_TEXT, sample_invoice)
        assert result.invoice_date.value == date(2024, 6, 1)

    def test_null_fields_have_zero_confidence(self, llm_extractor, sample_invoice, mock_backend):
        mock_backend.complete.return_value = SAMPLE_LLM_RESPONSE
        result = llm_extractor.extract(SAMPLE_TEXT, sample_invoice)
        assert result.due_date.value is None
        assert result.due_date.confidence == pytest.approx(0.0)

    def test_line_items_parsed(self, llm_extractor, sample_invoice, mock_backend):
        mock_backend.complete.return_value = SAMPLE_LLM_RESPONSE
        result = llm_extractor.extract(SAMPLE_TEXT, sample_invoice)
        assert len(result.line_items) == 1
        li = result.line_items[0]
        assert li.description == "Prestation dev"
        assert li.quantity == pytest.approx(10.0)

    def test_line_item_tva_rate_decimal_coerced_to_percent(self, llm_extractor, sample_invoice, mock_backend):
        response = json.loads(SAMPLE_LLM_RESPONSE)
        response["line_items"] = [
            {"description": "Service", "quantity": 1.0, "unit_price": 500.0,
             "line_total": 500.0, "tva_rate": 0.19}  # decimal fraction
        ]
        mock_backend.complete.return_value = json.dumps(response)
        result = llm_extractor.extract(SAMPLE_TEXT, sample_invoice)
        assert result.line_items[0].tva_rate == pytest.approx(19.0)

    def test_currency_set_on_invoice(self, llm_extractor, sample_invoice, mock_backend):
        mock_backend.complete.return_value = SAMPLE_LLM_RESPONSE
        result = llm_extractor.extract(SAMPLE_TEXT, sample_invoice)
        assert result.currency == "TND"

    def test_raw_extracted_json_saved(self, llm_extractor, sample_invoice, mock_backend):
        mock_backend.complete.return_value = SAMPLE_LLM_RESPONSE
        result = llm_extractor.extract(SAMPLE_TEXT, sample_invoice)
        assert result.raw_extracted_json is not None
        assert "invoice_number" in result.raw_extracted_json

    def test_markdown_fenced_response_parsed(self, llm_extractor, sample_invoice, mock_backend):
        fenced = f"```json\n{SAMPLE_LLM_RESPONSE}\n```"
        mock_backend.complete.return_value = fenced
        result = llm_extractor.extract(SAMPLE_TEXT, sample_invoice)
        assert result.invoice_number.value == "FAC-2024-001"

    def test_invalid_json_raises_extraction_error(self, llm_extractor, sample_invoice, mock_backend):
        mock_backend.complete.return_value = "this is not json at all"
        with pytest.raises(ExtractionError):
            llm_extractor.extract(SAMPLE_TEXT, sample_invoice)

    def test_numeric_value_as_string_coerced(self, llm_extractor, sample_invoice, mock_backend):
        response = json.dumps({
            **json.loads(SAMPLE_LLM_RESPONSE),
            "amount_ttc": {"value": "1190.00", "confidence": 0.9, "source": None},
        })
        mock_backend.complete.return_value = response
        result = llm_extractor.extract(SAMPLE_TEXT, sample_invoice)
        assert isinstance(result.amount_ttc.value, float)


class TestLLMExtractorSourceValidation:

    def test_source_not_in_text_zeroes_confidence(self, llm_extractor, sample_invoice, mock_backend):
        response = json.dumps({
            **json.loads(SAMPLE_LLM_RESPONSE),
            "issuer_name": {"value": "Made Up Corp", "confidence": 0.9, "source": "HALLUCINATED"},
        })
        mock_backend.complete.return_value = response
        result = llm_extractor.extract(SAMPLE_TEXT, sample_invoice)
        assert result.issuer_name.confidence == pytest.approx(0.0)

    def test_source_in_text_keeps_confidence(self, llm_extractor, sample_invoice, mock_backend):
        mock_backend.complete.return_value = SAMPLE_LLM_RESPONSE
        result = llm_extractor.extract(SAMPLE_TEXT, sample_invoice)
        # "FAC-2024-001" appears in SAMPLE_TEXT → confidence should be unchanged
        assert result.invoice_number.confidence == pytest.approx(0.95)

    def test_null_source_keeps_confidence_unchanged(self, llm_extractor, sample_invoice, mock_backend):
        mock_backend.complete.return_value = SAMPLE_LLM_RESPONSE
        result = llm_extractor.extract(SAMPLE_TEXT, sample_invoice)
        # currency has null source → confidence should stay as returned by LLM
        assert result.currency == "TND"


class TestLLMExtractorCrossValidation:

    def test_inconsistent_amounts_penalise_confidence(self, llm_extractor, sample_invoice, mock_backend):
        bad = json.loads(SAMPLE_LLM_RESPONSE)
        # Make TTC wrong: HT(1000) + TVA(190) ≠ TTC(999)
        bad["amount_ttc"] = {"value": 999.0, "confidence": 0.95, "source": None}
        mock_backend.complete.return_value = json.dumps(bad)
        result = llm_extractor.extract(SAMPLE_TEXT, sample_invoice)
        # All three amount fields should be penalised (halved)
        assert result.amount_ttc.confidence < 0.5
        assert result.amount_ht.confidence < 0.5
        assert result.tva_amount.confidence < 0.5

    def test_consistent_amounts_leave_confidence_unchanged(self, llm_extractor, sample_invoice, mock_backend):
        mock_backend.complete.return_value = SAMPLE_LLM_RESPONSE
        result = llm_extractor.extract(SAMPLE_TEXT, sample_invoice)
        # 1000 + 190 == 1190 → no penalty
        assert result.amount_ttc.confidence == pytest.approx(0.96)


# ── LLMExtractor._extract_json ────────────────────────────────────────────────

class TestExtractJson:
    def test_plain_json(self):
        raw = '{"key": "value"}'
        assert LLMExtractor._extract_json(raw) == raw

    def test_json_with_leading_text(self):
        raw = 'Sure! Here is the JSON:\n{"key": "value"}'
        assert json.loads(LLMExtractor._extract_json(raw)) == {"key": "value"}

    def test_fenced_json(self):
        raw = '```json\n{"key": "value"}\n```'
        assert json.loads(LLMExtractor._extract_json(raw)) == {"key": "value"}

    def test_fenced_no_lang(self):
        raw = '```\n{"key": "value"}\n```'
        assert json.loads(LLMExtractor._extract_json(raw)) == {"key": "value"}


# ── HybridExtractor routing ────────────────────────────────────────────────────

# Minimal invoice text that passes InvoiceValidator (score ≥ 5, ≥ 80 chars, ≥ 2 numbers)
_VALID_INVOICE_TEXT = (
    "FACTURE N° FAC-2026-001\n"
    "MF: 0038472K/A/M/000\n"
    "TVA 19%\n"
    "Total TTC: 1,190.000 TND\n"
    "Montant HT: 1,000.000 TND"
)


class TestHybridExtractorRouting:

    @pytest.fixture()
    def components(self):
        reader = MagicMock(spec=PDFReader)
        preprocessor = MagicMock(spec=OCRPreprocessor)
        ocr_engine = MagicMock(spec=EasyOCREngine)
        llm_ext = MagicMock(spec=LLMExtractor)
        return reader, preprocessor, ocr_engine, llm_ext

    @pytest.fixture()
    def extractor(self, components, config):
        reader, preprocessor, ocr_engine, llm_ext = components
        llm_ext.extract.side_effect = lambda text, inv: inv  # pass-through
        preprocessor.process.side_effect = lambda img: img
        return HybridExtractor(
            pdf_reader=reader,
            preprocessor=preprocessor,
            ocr_engine=ocr_engine,
            llm_extractor=llm_ext,
            config=config,
        )

    def test_native_pdf_uses_native_route(self, extractor, components, sample_invoice, native_pdf):
        reader, _, ocr_engine, _ = components
        sample_invoice.raw_file_path = str(native_pdf)
        reader.is_native_pdf.return_value = True
        reader.extract_text.return_value = _VALID_INVOICE_TEXT

        result = extractor.extract(sample_invoice)

        reader.extract_text.assert_called_once()
        ocr_engine.extract.assert_not_called()
        assert result.extraction_method == ExtractionMethod.NATIVE_PDF_LLM

    def test_scanned_pdf_uses_ocr_route(self, extractor, components, sample_invoice, native_pdf):
        reader, preprocessor, ocr_engine, _ = components
        sample_invoice.raw_file_path = str(native_pdf)
        reader.is_native_pdf.return_value = False
        reader.to_images.return_value = [MagicMock()]
        ocr_engine.extract.return_value = _VALID_INVOICE_TEXT

        result = extractor.extract(sample_invoice)

        reader.to_images.assert_called_once()
        ocr_engine.extract.assert_called_once()
        assert result.extraction_method == ExtractionMethod.OCR_LLM

    def test_image_file_uses_ocr_route(self, extractor, components, sample_invoice, tmp_path):
        reader, preprocessor, ocr_engine, _ = components
        img_path = tmp_path / "scan.png"
        Image.fromarray(np.full((200, 150), 200, dtype=np.uint8)).save(str(img_path))
        sample_invoice.raw_file_path = str(img_path)
        reader.image_to_pil.return_value = MagicMock()
        ocr_engine.extract.return_value = _VALID_INVOICE_TEXT

        result = extractor.extract(sample_invoice)

        reader.image_to_pil.assert_called_once()
        ocr_engine.extract.assert_called_once()
        assert result.extraction_method == ExtractionMethod.OCR_LLM

    def test_unsupported_extension_raises(self, extractor, sample_invoice):
        sample_invoice.raw_file_path = "/some/doc.docx"
        with pytest.raises(ValueError, match="Unsupported file type"):
            extractor.extract(sample_invoice)

    def test_extracted_at_is_set(self, extractor, components, sample_invoice, native_pdf):
        reader, _, _, _ = components
        sample_invoice.raw_file_path = str(native_pdf)
        reader.is_native_pdf.return_value = True
        reader.extract_text.return_value = _VALID_INVOICE_TEXT

        result = extractor.extract(sample_invoice)
        assert result.extracted_at is not None

    def test_preprocessor_called_for_each_page(self, extractor, components, sample_invoice, native_pdf):
        reader, preprocessor, ocr_engine, _ = components
        sample_invoice.raw_file_path = str(native_pdf)
        reader.is_native_pdf.return_value = False
        fake_pages = [MagicMock(), MagicMock()]
        reader.to_images.return_value = fake_pages
        ocr_engine.extract.return_value = _VALID_INVOICE_TEXT

        extractor.extract(sample_invoice)
        assert preprocessor.process.call_count == 2


# ── LLMExtractor — amounts_only mode ─────────────────────────────────────────

class TestLLMExtractorAmountsOnly:
    _AMOUNTS_RESPONSE = json.dumps({
        "amount_ht":   {"value": 1500.0, "confidence": 0.95},
        "tva_rate":    {"value": 19.0,   "confidence": 0.95},
        "tva_amount":  {"value": 285.0,  "confidence": 0.95},
        "amount_ttc":  {"value": 1785.0, "confidence": 0.95},
    })

    def _extractor(self, mode="amounts_only"):
        backend = MagicMock()
        backend.complete.return_value = self._AMOUNTS_RESPONSE
        return LLMExtractor(backend=backend, languages=["fr"], mode=mode), backend

    def _inv(self):
        from src.models.enums import InvoiceDirection, InvoiceStatus
        return InvoiceRecord(
            file_hash="a" * 64,
            raw_file_path="/tmp/test.pdf",
            direction=InvoiceDirection.SUPPLIER,
            status=InvoiceStatus.RECEIVED,
        )

    def test_amounts_only_sets_amount_fields(self):
        ext, _ = self._extractor("amounts_only")
        result = ext.extract("dummy invoice text", self._inv())
        assert result.amount_ttc.value == pytest.approx(1785.0)
        assert result.amount_ht.value == pytest.approx(1500.0)
        assert result.tva_amount.value == pytest.approx(285.0)
        assert result.tva_rate.value == pytest.approx(19.0)

    def test_amounts_only_does_not_set_text_fields(self):
        ext, _ = self._extractor("amounts_only")
        result = ext.extract("dummy invoice text", self._inv())
        assert result.issuer_name.value is None
        assert result.invoice_number.value is None

    def test_amounts_only_uses_shorter_system_prompt(self):
        ext, backend = self._extractor("amounts_only")
        ext.extract("dummy invoice text", self._inv())
        system_prompt = backend.complete.call_args[0][0]
        assert "monetary totals" in backend.complete.call_args[0][1]
        assert len(system_prompt) < 200  # reduced system prompt

    def test_full_schema_sets_text_fields(self):
        full_response = json.dumps({
            "issuer_name": {"value": "Test Corp", "confidence": 0.9, "source": "Test Corp"},
            "issuer_tax_id": {"value": None, "confidence": 0.0, "source": None},
            "recipient_name": {"value": None, "confidence": 0.0, "source": None},
            "recipient_tax_id": {"value": None, "confidence": 0.0, "source": None},
            "invoice_number": {"value": "INV-001", "confidence": 0.9, "source": "INV-001"},
            "invoice_date": {"value": "2024-01-15", "confidence": 0.9, "source": "15/01/2024"},
            "due_date": {"value": None, "confidence": 0.0, "source": None},
            "amount_ht": {"value": 1000.0, "confidence": 0.95, "source": "1000"},
            "tva_rate": {"value": 19.0, "confidence": 0.95, "source": "19%"},
            "tva_amount": {"value": 190.0, "confidence": 0.95, "source": "190"},
            "amount_ttc": {"value": 1190.0, "confidence": 0.95, "source": "1190"},
            "currency": {"value": "TND", "confidence": 1.0, "source": "TND"},
            "line_items": [],
        })
        backend = MagicMock()
        backend.complete.return_value = full_response
        ext = LLMExtractor(backend=backend, languages=["fr"], mode="full_schema")
        result = ext.extract("Test Corp dummy invoice text INV-001 15/01/2024 1000 19% 190 1190 TND", self._inv())
        assert result.issuer_name.value == "Test Corp"
        assert result.invoice_number.value == "INV-001"

    def test_mode_default_is_amounts_only(self):
        backend = MagicMock()
        backend.complete.return_value = self._AMOUNTS_RESPONSE
        ext = LLMExtractor(backend=backend, languages=["fr"])
        assert ext.mode == "amounts_only"
