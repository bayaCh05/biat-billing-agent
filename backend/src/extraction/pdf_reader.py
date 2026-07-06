from __future__ import annotations

import re
from pathlib import Path


def _contains_arabic(text: str) -> bool:
    return bool(re.search(r"[؀-ۿ]", text))


def _fix_arabic_text(text: str) -> str:
    """Reshape and reorder Arabic characters for correct reading direction."""
    import arabic_reshaper
    from bidi.algorithm import get_display
    return get_display(arabic_reshaper.reshape(text))


class PDFReader:
    """Extracts text and images from PDF files using pdfplumber + PyMuPDF."""

    def __init__(self, min_chars: int = 50, min_quality_ratio: float = 0.85) -> None:
        self.min_chars = min_chars
        self.min_quality_ratio = min_quality_ratio

    def is_native_pdf(self, file_path: str) -> bool:
        """Return True if the PDF has a usable embedded text layer."""
        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                sample = ""
                for page in pdf.pages[:3]:  # inspect first 3 pages
                    sample += page.extract_text() or ""
                    if len(sample) >= self.min_chars * 2:
                        break

            if len(sample) < self.min_chars:
                return False

            printable = sum(1 for c in sample if c.isprintable() and not c.isspace())
            total = sum(1 for c in sample if not c.isspace())
            ratio = printable / total if total else 0.0
            return ratio >= self.min_quality_ratio
        except Exception:
            return False

    def extract_text(self, file_path: str) -> str:
        """Extract full text from a native PDF. Fixes Arabic bidi ordering."""
        import pdfplumber
        pages_text: list[str] = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                if _contains_arabic(text):
                    text = _fix_arabic_text(text)
                pages_text.append(text)
        return "\n\n".join(pages_text).strip()

    def to_images(self, file_path: str, dpi: int = 300) -> list:
        """Render every PDF page to a PIL Image at the given DPI."""
        import fitz
        from PIL import Image
        import io

        images: list[Image.Image] = []
        doc = fitz.open(file_path)
        zoom = dpi / 72.0  # fitz default is 72 DPI
        matrix = fitz.Matrix(zoom, zoom)
        for page in doc:
            pix = page.get_pixmap(matrix=matrix, colorspace=fitz.csGRAY)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            images.append(img)
        doc.close()
        return images

    def image_to_pil(self, file_path: str) -> object:
        """Load a non-PDF image file as a PIL Image."""
        from PIL import Image
        return Image.open(file_path)
