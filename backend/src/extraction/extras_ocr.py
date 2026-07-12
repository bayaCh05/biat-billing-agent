"""Optional EasyOCR engine — not used in production (easyocr not installed).

Kept here for reference. To activate:
  1. pip install easyocr
  2. In config/settings.yaml set ocr_engine: easyocr
  3. In src/agent/config_loader.py add this engine to _OCR_ENGINES
"""
from __future__ import annotations

import numpy as np

from src.extraction.ocr_engine import OCREngineBase


class EasyOCREngine(OCREngineBase):
    """EasyOCR-based engine. Supports Arabic and French out of the box.

    The underlying Reader is initialised lazily on first use to avoid a slow
    import and model-download at startup.
    """

    def __init__(self, languages: list[str]) -> None:
        self.languages = languages
        self._reader = None

    def extract(self, images: list, languages: list[str] | None = None) -> str:
        reader = self._get_reader()
        page_texts: list[str] = []
        for image in images:
            arr = np.array(image)
            results: list[str] = reader.readtext(arr, detail=0, paragraph=True)
            page_texts.append("\n".join(results))
        return "\n\n".join(page_texts)

    def _get_reader(self):
        if self._reader is None:
            import easyocr
            self._reader = easyocr.Reader(self.languages, gpu=False, verbose=False)
        return self._reader
