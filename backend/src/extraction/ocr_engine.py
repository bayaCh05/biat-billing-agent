from __future__ import annotations

from abc import ABC, abstractmethod


# Mapping from generic language codes to Tesseract's lang codes
_TESSERACT_LANG_MAP = {"fr": "fra", "ar": "ara", "en": "eng"}

# Unicode bidi direction control characters.
# Tesseract injects these when processing RTL (Arabic) text alongside LTR
# (French/Latin) text.  They are invisible but corrupt line-level parsing
# in the HeaderExtractor and downstream regex patterns.
_BIDI_CHARS = (
    '‎',  # LEFT-TO-RIGHT MARK
    '‏',  # RIGHT-TO-LEFT MARK
    '‪',  # LEFT-TO-RIGHT EMBEDDING
    '‫',  # RIGHT-TO-LEFT EMBEDDING
    '‬',  # POP DIRECTIONAL FORMATTING
    '‭',  # LEFT-TO-RIGHT OVERRIDE
    '‮',  # RIGHT-TO-LEFT OVERRIDE
    '⁦',  # LEFT-TO-RIGHT ISOLATE
    '⁧',  # RIGHT-TO-LEFT ISOLATE
    '⁨',  # FIRST STRONG ISOLATE
    '⁩',  # POP DIRECTIONAL ISOLATE
)
_BIDI_TABLE = str.maketrans('', '', ''.join(_BIDI_CHARS))


def _strip_bidi(text: str) -> str:
    return text.translate(_BIDI_TABLE)


class OCREngineBase(ABC):
    @abstractmethod
    def extract(self, images: list, languages: list[str]) -> str:
        """Run OCR on a list of PIL Images. Returns concatenated page text."""


class TesseractEngine(OCREngineBase):
    """pytesseract-based OCR engine.

    Language codes are translated from generic ('fr', 'ar') to Tesseract's
    format ('fra', 'ara') automatically.  Falls back to English if requested
    language packs are not installed.

    OCR strategy for bilingual (Arabic + French) documents
    -------------------------------------------------------
    Running Tesseract with combined 'fra+ara' causes bidi direction markers
    to be injected throughout the output, which corrupts line-level parsing.
    Instead, when Arabic is in the language list we run TWO separate passes:

      Pass 1 — French only ('fra'):  extracts Latin-script structured data
               (invoice numbers, amounts, labels, dates).
      Pass 2 — Arabic only ('ara'):  extracts Arabic descriptions if present.

    The two passes are concatenated with a separator so downstream consumers
    can distinguish them.  If only one language is requested the standard
    single-pass path is used.
    """

    # --oem 1  → LSTM engine only (better character accuracy than legacy CRF)
    # --psm 3  → fully automatic page segmentation (handles tables + columns)
    _TESS_CONFIG = "--oem 1 --psm 3"

    def __init__(self, languages: list[str]) -> None:
        self.languages = languages

    def extract(self, images: list, languages: list[str] | None = None) -> str:
        import pytesseract
        langs = languages or self.languages
        available = self._get_available(pytesseract)

        tess_langs = [_TESSERACT_LANG_MAP.get(l, l) for l in langs]
        tess_langs = [l for l in tess_langs if l in available]
        if not tess_langs:
            tess_langs = ["eng"] if "eng" in available else list(available)[:1]

        has_arabic = "ara" in tess_langs
        has_latin  = any(l in tess_langs for l in ("fra", "eng"))

        if has_arabic and has_latin:
            return self._bilingual_extract(pytesseract, images, tess_langs)
        else:
            return self._single_pass(pytesseract, images, "+".join(tess_langs))

    # ── Extraction paths ──────────────────────────────────────────────────────

    def _single_pass(self, pytesseract, images: list, lang_str: str) -> str:
        pages = []
        for image in images:
            raw = pytesseract.image_to_string(image, lang=lang_str,
                                              config=self._TESS_CONFIG)
            pages.append(_strip_bidi(raw))
        return "\n\n".join(pages)

    def _bilingual_extract(self, pytesseract, images: list,
                           tess_langs: list[str]) -> str:
        """Two-pass extraction: Latin script first, Arabic second.

        Keeps bidi markers out of the Latin pass (where structured invoice
        data lives) while still capturing Arabic text in a separate block.
        """
        latin_langs = [l for l in tess_langs if l != "ara"]
        latin_str   = "+".join(latin_langs) if latin_langs else "fra"
        arabic_str  = "ara"

        latin_pages, arabic_pages = [], []
        for image in images:
            latin_raw = pytesseract.image_to_string(image, lang=latin_str,
                                                    config=self._TESS_CONFIG)
            latin_pages.append(_strip_bidi(latin_raw))

            arabic_raw = pytesseract.image_to_string(image, lang=arabic_str,
                                                     config=self._TESS_CONFIG)
            arabic_pages.append(_strip_bidi(arabic_raw))

        latin_text  = "\n\n".join(latin_pages).strip()
        arabic_text = "\n\n".join(arabic_pages).strip()

        if arabic_text:
            return latin_text + "\n\n[ARABIC]\n" + arabic_text
        return latin_text

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _get_available(pytesseract) -> set[str]:
        try:
            return set(pytesseract.get_languages())
        except Exception:
            return {"eng"}
