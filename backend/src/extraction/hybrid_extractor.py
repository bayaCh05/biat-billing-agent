from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.extraction.base import ExtractorBase
from src.extraction.header_extractor import HeaderExtractor
from src.extraction.invoice_validator import InvoiceValidator, NotAnInvoiceError
from src.extraction.llm_extractor import LLMExtractor
from src.extraction.ocr_engine import OCREngineBase
from src.extraction.ocr_preprocessor import OCRPreprocessor
from src.extraction.pdf_reader import PDFReader
from src.models.enums import ExtractionMethod
from src.models.invoice import ConfidenceField, InvoiceRecord
from src.utils.logging import get_logger

logger = get_logger(__name__)

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}
_header_extractor = HeaderExtractor()
_validator = InvoiceValidator()


class HybridExtractor(ExtractorBase):
    """Routes each document to the correct extraction path.

    Decision tree:
      PDF with clean text layer  → PDFReader → LLMExtractor
      PDF with garbled / no text → PDF→images → OCRPreprocessor → OCREngine → LLMExtractor
      Image file                 → OCRPreprocessor → OCREngine → LLMExtractor
    """

    def __init__(
        self,
        pdf_reader: PDFReader,
        preprocessor: OCRPreprocessor,
        ocr_engine: OCREngineBase,
        llm_extractor: LLMExtractor,
        config: dict,
    ) -> None:
        self.pdf_reader = pdf_reader
        self.preprocessor = preprocessor
        self.ocr_engine = ocr_engine
        self.llm_extractor = llm_extractor
        self.languages: list[str] = config["extraction"]["languages"]
        self.render_dpi: int = config["extraction"]["render_dpi"]

    def extract(self, invoice: InvoiceRecord) -> InvoiceRecord:
        file_path = invoice.raw_file_path
        suffix = Path(file_path).suffix.lower()

        if suffix == ".pdf":
            text, method = self._extract_pdf(file_path)
        elif suffix in _IMAGE_EXTENSIONS:
            text, method = self._extract_image(file_path)
        else:
            raise ValueError(f"Unsupported file type: {suffix}")

        logger.info(
            "text_extracted",
            invoice_id=str(invoice.id),
            method=method.value,
            chars=len(text),
        )

        invoice.extraction_method = method
        invoice.raw_extracted_text = text

        # ── Pre-extraction invoice validation ─────────────────────────────────
        # Rejects non-invoice documents (screenshots, presentations, etc.)
        # before spending time on LLM calls.
        try:
            _validator.validate(text, filename=Path(file_path).name)
        except NotAnInvoiceError as e:
            logger.warning(
                "invoice_validation_failed",
                invoice_id=str(invoice.id),
                reason=e.reason,
                text_sample=e.text_sample[:100],
            )
            raise

        # ── Rules-based header extraction (runs before LLM) ───────────────────
        # Fills issuer_name, invoice_number, invoice_date from text patterns.
        # The LLM only overwrites these if it returns a higher-confidence value.
        header = _header_extractor.extract(text)
        if header['issuer_name']:
            invoice.issuer_name = ConfidenceField(
                value=header['issuer_name'],
                confidence=header.get('issuer_confidence', 0.65),
                source='header_rules',
            )
            logger.debug("header_extracted_issuer", value=header['issuer_name'],
                         invoice_id=str(invoice.id))
        if header['invoice_number']:
            invoice.invoice_number = ConfidenceField(
                value=header['invoice_number'], confidence=0.85, source='header_rules'
            )
            logger.debug("header_extracted_number", value=header['invoice_number'],
                         invoice_id=str(invoice.id))
        if header['invoice_date']:
            invoice.invoice_date = ConfidenceField(
                value=header['invoice_date'], confidence=0.90, source='header_rules'
            )
            logger.debug("header_extracted_date", value=str(header['invoice_date']),
                         invoice_id=str(invoice.id))

        # ── LLM extraction (amounts + any remaining fields) ───────────────────
        invoice = self.llm_extractor.extract(text, invoice)
        invoice.extracted_at = datetime.now(tz=timezone.utc)
        return invoice

    # ── PDF path ──────────────────────────────────────────────────────────────

    def _extract_pdf(self, file_path: str) -> tuple[str, ExtractionMethod]:
        if self.pdf_reader.is_native_pdf(file_path):
            logger.debug("pdf_route", path=file_path, route="native_text")
            text = self.pdf_reader.extract_text(file_path)
            return text, ExtractionMethod.NATIVE_PDF_LLM
        else:
            logger.debug("pdf_route", path=file_path, route="ocr_fallback")
            images = self.pdf_reader.to_images(file_path, dpi=self.render_dpi)
            text = self._run_ocr(images)
            return text, ExtractionMethod.OCR_LLM

    # ── Image path ────────────────────────────────────────────────────────────

    def _extract_image(self, file_path: str) -> tuple[str, ExtractionMethod]:
        image = self.pdf_reader.image_to_pil(file_path)
        text = self._run_ocr([image])
        return text, ExtractionMethod.OCR_LLM

    # ── Shared OCR pipeline ───────────────────────────────────────────────────

    def _run_ocr(self, images: list) -> str:
        processed = [self.preprocessor.process(img) for img in images]
        return self.ocr_engine.extract(processed, self.languages)
