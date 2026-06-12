from __future__ import annotations

from abc import ABC, abstractmethod


# Mapping from generic language codes to Tesseract's lang codes
_TESSERACT_LANG_MAP = {"fr": "fra", "ar": "ara", "en": "eng"}


class OCREngineBase(ABC):
    @abstractmethod
    def extract(self, images: list, languages: list[str]) -> str:
        """Run OCR on a list of PIL Images. Returns concatenated page text."""


class TesseractEngine(OCREngineBase):
    """pytesseract-based OCR engine.

    Language codes are translated from generic ('fr', 'ar') to Tesseract's
    format ('fra', 'ara') automatically. Falls back to English if requested
    language packs are not installed.
    """

    def __init__(self, languages: list[str]) -> None:
        self.languages = languages

    def extract(self, images: list, languages: list[str] | None = None) -> str:
        import pytesseract
        langs = languages or self.languages
        tess_lang = self._resolve_lang(pytesseract, langs)
        page_texts: list[str] = []
        for image in images:
            text = pytesseract.image_to_string(image, lang=tess_lang)
            page_texts.append(text)
        return "\n\n".join(page_texts)

    @staticmethod
    def _resolve_lang(pytesseract, langs: list[str]) -> str:
        """Return the best available Tesseract lang string, falling back to eng."""
        try:
            available = set(pytesseract.get_languages())
        except Exception:
            return "eng"
        wanted = [_TESSERACT_LANG_MAP.get(l, l) for l in langs]
        usable = [l for l in wanted if l in available]
        if not usable:
            usable = ["eng"] if "eng" in available else list(available)[:1]
        return "+".join(usable)
