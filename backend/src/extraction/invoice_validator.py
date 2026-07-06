"""Pre-extraction validator: rejects non-invoice PDFs before OCR/LLM are called."""
from __future__ import annotations

import re

import structlog

logger = structlog.get_logger(__name__)


class NotAnInvoiceError(ValueError):
    """Raised when a document is not a recognisable invoice."""

    def __init__(self, reason: str, text_sample: str = "") -> None:
        self.reason = reason
        self.text_sample = text_sample
        super().__init__(f"Not an invoice: {reason}")


class InvoiceValidator:
    """Scores a document's raw text to decide whether it is a supplier invoice.

    Uses a point-based system.  Raises NotAnInvoiceError immediately when:
      - content matches a known non-invoice pattern (entertainment, academic…)
      - text is too short to contain meaningful invoice data
      - cumulative invoice-signal score is below _MIN_SCORE
      - too few numeric values are present (invoices always have amounts)
    """

    # ── Immediate-reject patterns (checked against lowercased text) ───────────
    # Any match stops processing immediately — no scoring needed.
    _REJECT_IMMEDIATELY = [
        r'bridgerton|netflix|disney|hulu|amazon\s+prime',
        r'episode\s+\d|season\s+\d|chapter\s+\d',
        r'©\s+\d{4}\s+(?:netflix|disney|warner)',
        r'all\s+rights\s+reserved.*entertainment',
        r'screenplay|script\s+by|directed\s+by',
        r'university|université.*cours|lecture\s+notes',
        r'curriculum\s+vitae|cv\s+|resume\s+of',
    ]

    # ── Positive invoice signals ───────────────────────────────────────────────
    # (points, compiled-pattern) — matched against lowercased text.
    _INVOICE_SIGNALS: list[tuple[int, str]] = [
        # Strong (3 pts)
        (3, r'\b(?:facture|invoice|fatura)\b'),
        (3, r'\b(?:montant\s+(?:ht|ttc)|amount\s+due)\b'),
        (3, r'\b(?:tva|t\.v\.a|taxe\s+sur\s+la\s+valeur)\b'),
        (3, r'\b(?:matricule\s+fiscal|mf\s*:)\b'),
        (3, r'\b(?:total\s+(?:ht|ttc|à\s+payer))\b'),
        # Medium (2 pts)
        (2, r'\b(?:fournisseur|supplier|vendeur)\b'),
        (2, r'\b(?:client|acheteur|buyer)\b'),
        (2, r'\b(?:date\s+(?:de\s+)?(?:facture|[eé]mission))\b'),
        (2, r'\b(?:[eé]ch[eé]ance|due\s+date|paiement)\b'),
        (2, r'\btnd\b|\bdinars?\b'),
        (2, r'(?:fac|fc|inv|fact)[-/]\d{4}'),
        # Weak (1 pt)
        (1, r'\b(?:d[eé]signation|description|lib[eé]ll[eé])\b'),
        (1, r'\b(?:quantit[eé]|qt[eé]|qty)\b'),
        (1, r'\b(?:prix\s+unitaire|unit\s+price|p\.u\.)\b'),
        (1, r'\b(?:remise|discount|r[eé]duction)\b'),
        (1, r'\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2,3})\s*tnd\b'),

        # ── TTN / Tunisian public utility formats ─────────────────────────────
        # Strong (3 pts) — highly specific to invoices
        (3, r'\bf\.?a\.?c\.?t\.?u\.?r\.?e\b'),        # "f.a.c.t.u.r.e" (dotted OCR)
        (3, r'\bt\.?v\.?a\.?\b'),                       # "t.v.a", "t.v.a.", "t.v.a.%"
        (3, r'\bh\.?t\.?v\.?a\.?\b'),                  # "htva", "h.t.v.a", "h.t.v.a."
        (3, r'\bt\.?t\.?c\.?\b'),                       # "ttc", "t.t.c", "t.t.c."
        (3, r'matricule\s+fiscal'),                     # long form (not just "MF")
        (3, r'r[eé]f[eé]rence\s+unique'),              # TTN electronic reference
        (3, r'droit\s+de\s+timbre'),                    # Tunisian stamp tax — invoices only
        (3, r'tunisie\s+tradenet|tradenet\.com'),       # TTN issuer header
        # Medium (2 pts)
        (2, r'facture\s+[nN]\s*[°o]?\s*\d+'),         # "Facture N 8116" (OCR drops °)
        (2, r'\bmontant\s+t\.?t\.?c\.?\b'),            # "Montant T.T.C"
        (2, r'\btotal\s+h\.?t\.?v\.?a\.?\b'),          # "Total H.T.V.A."
        (2, r'p\.?u\.?h\.?t\.?v\.?a\.?'),              # "P.U.H.T.V.A." (unit price header)
        (2, r'\bdinars?\s+et\b|\bmillimes?\b'),         # amount in words — Tunisian only
        (2, r'arr[eê]t[eé]\s+la\s+pr[eé]sente\s+facture'),  # standard Tunisian footer
        # Weak (1 pt)
        (1, r'coupon\s+de\s+versement|bulletin\s+de\s+versement'),
        (1, r'p[eé]riode\s*:\s*du'),                   # "Periode : du" billing period
    ]

    _MIN_SCORE   = 3    # cumulative signal points required (was 5)
    _MIN_CHARS   = 50   # minimum non-whitespace text length (was 80)
    _MIN_NUMBERS = 1    # minimum formatted numeric values for borderline docs

    # Documents scoring >= this threshold are trusted by keyword signals alone.
    # Poor OCR on real invoices can garble all monetary amounts while leaving
    # French/Arabic invoice keywords readable — the numeric check would then
    # produce a false rejection.  High-confidence docs bypass it entirely.
    _BYPASS_NUMERIC_AT_SCORE = 6

    # numeric amounts: handles Tunisian 3-decimal format (1,420.000)
    _NUMERIC_RE = re.compile(r'\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,3})\b')

    def validate(self, text: str, filename: str = "") -> None:
        """Check whether *text* looks like an invoice.

        Raises NotAnInvoiceError with a specific reason if not.
        Returns None silently when validation passes.

        Checks run in priority order so the most informative reason is reported:
          1. Immediate reject  — known non-invoice markers
          2. Length            — too short to contain invoice data
          3. Score threshold   — not enough invoice keywords
          4. Numeric values    — no monetary amounts found
        """
        text_lower = text.lower()

        # ── 1. Immediate reject ───────────────────────────────────────────────
        for pattern in self._REJECT_IMMEDIATELY:
            if re.search(pattern, text_lower):
                raise NotAnInvoiceError(
                    reason=f"non_invoice_content: {pattern}",
                    text_sample=text[:200],
                )

        # ── 2. Length check ───────────────────────────────────────────────────
        if len(text.strip()) < self._MIN_CHARS:
            raise NotAnInvoiceError(
                reason="text_too_short",
                text_sample=text[:100],
            )

        # ── 3. Score positive signals ─────────────────────────────────────────
        score = 0
        matched_signals: list[str] = []
        for points, pattern in self._INVOICE_SIGNALS:
            if re.search(pattern, text_lower):
                score += points
                matched_signals.append(pattern)

        if score < self._MIN_SCORE:
            raise NotAnInvoiceError(
                reason=f"low_invoice_score_{score}_of_{self._MIN_SCORE}",
                text_sample=text[:200],
            )

        # ── 4. Numeric value count (skipped for high-confidence docs) ────────
        numbers_found = len(self._NUMERIC_RE.findall(text))
        if score < self._BYPASS_NUMERIC_AT_SCORE and numbers_found < self._MIN_NUMBERS:
            raise NotAnInvoiceError(
                reason="insufficient_numeric_values",
                text_sample=text[:200],
            )

        logger.debug(
            "invoice_validation_passed",
            score=score,
            signals_matched=len(matched_signals),
            numbers_found=numbers_found,
            filename=filename,
        )
