"""Rules-based extraction of issuer_name, invoice_number, invoice_date from raw text.

Runs BEFORE the LLM call so these three fields are available even in
amounts_only mode where the LLM only handles monetary totals.
"""
from __future__ import annotations

import re
from datetime import date

import structlog

logger = structlog.get_logger(__name__)


class HeaderExtractor:
    """Heuristic extraction of three header fields from Tunisian invoice text."""

    # ── Non-invoice content markers ───────────────────────────────────────────
    _NON_INVOICE_MARKERS = [
        "bridgerton", "netflix", "episode", "season",
        "chapter", "disney", "hulu", "amazon prime",
    ]

    # ── Invoice number patterns ───────────────────────────────────────────────
    # Ordered: most-specific first to avoid false positives.
    _INV_PATTERNS: list[str] = [
        # Explicit "N°" or "No" label followed by an alphanumeric code
        r'N[°o°]\s+([A-Z0-9][A-Z0-9\-/]{3,25})',
        # "Numéro de facture: FAC-2026-0042"
        r'[Nn]um[eé]ro\s+de\s+facture\s*:?\s*([A-Z0-9][A-Z0-9\-/]{3,25})',
        # "Facture N° 2026-042"
        r'[Ff]acture\s+N[°o°]\s*:?\s*([A-Z0-9][A-Z0-9\-/]{3,25})',
        # Explicit prefixes: FAC-, FC-, INV-, FACT-
        r'\b((?:FAC|FC|INV|FACT)[-/]\d{4}[-/][A-Z0-9\-]{2,15})\b',
        # Generic alphanum code with 4-digit year in it (e.g. STEG-2026-05-00847)
        r'\b([A-Z]{2,6}-\d{4}-[A-Z0-9]{1,6}-[0-9]{3,6})\b',
        # Ref / Reference label
        r'[Rr][eé]f(?:\.|\s|érence)?\s*:?\s*([A-Z0-9][A-Z0-9\-/]{3,20})',
        # Tunisian formats seen in practice
        r'(?:Facture|Fact\.?)\s*[Nn][°o]\s*:?\s*(\w[\w\-/]{2,20})',
        r'[Nn][°o°]\s*[Ff]acture\s*:?\s*(\w[\w\-/]{2,20})',
        r'R[eé]f(?:\.?\s*[Ff]acture)?\s*:?\s*([A-Z0-9][\w\-/]{2,20})',
        # Plain year-number: only match a current-era year (202x) to avoid fiscal IDs like 0147/2018
        r'\b(202[0-9][-/]\d{3,6})\b',
        r'(?:Invoice|INV)\s*#?\s*:?\s*(\w[\w\-/]{2,20})',
    ]

    # ── French month names ────────────────────────────────────────────────────
    _MONTHS_FR: dict[str, int] = {
        'janvier': 1, 'février': 2, 'mars': 3, 'avril': 4,
        'mai': 5, 'juin': 6, 'juillet': 7, 'août': 8,
        'septembre': 9, 'octobre': 10, 'novembre': 11, 'décembre': 12,
        'jan': 1, 'fév': 2, 'mar': 3, 'avr': 4,
        'jun': 6, 'jul': 7, 'aoû': 8, 'sep': 9,
        'oct': 10, 'nov': 11, 'déc': 12,
    }

    # ── Prefixes that disqualify a line as the issuer name ───────────────────
    _SKIP_PREFIXES = (
        "tel", "tél", "fax", "email", "e-mail", "www", "http",
        "bp ", "b.p.", "mf:", "mf :", "matricule", "rib", "iban",
        "date", "facture", "n°", "no ", "ref", "réf",
        "fournisseur", "client", "devise", "montant", "total",
        "description", "désignation", "qté", "quantité",
        "ht", "tva", "ttc",
        "page", "objet", "à ", "de ", "monsieur", "madame",
        "tunis", "rue", "av ", "av.", "avenue", "zone",
        "rc ", "rne ", "po box",
    )
    _SKIP_EXACT = frozenset({
        "facture", "fournisseur", "client", "devise",
        "ht", "tva", "ttc", "invoice",
    })

    def _is_likely_not_invoice(self, text: str) -> bool:
        if len(text.strip()) < 50:
            return True
        text_lower = text.lower()
        return any(m in text_lower for m in self._NON_INVOICE_MARKERS)

    def extract(self, text: str, invoice_id: str = "unknown") -> dict:
        if self._is_likely_not_invoice(text):
            logger.warning("header_non_invoice_detected", text_sample=text[:100])
            return {
                'issuer_name': None, 'issuer_confidence': 0.0,
                'invoice_number': None, 'invoice_date': None,
            }

        issuer_name, issuer_conf = self._extract_issuer(text)
        result = {
            'issuer_name':       issuer_name,
            'issuer_confidence': issuer_conf,
            'invoice_number':    self._extract_invoice_number(text),
            'invoice_date':      self._extract_date(text),
        }
        logger.debug("header_extraction_result",
                     invoice_id=invoice_id,
                     issuer=result['issuer_name'],
                     issuer_conf=issuer_conf,
                     number=result['invoice_number'],
                     date=str(result['invoice_date']))
        return result

    # ── Issuer name ───────────────────────────────────────────────────────────

    def _extract_issuer(self, text: str) -> tuple[str | None, float]:
        """Return (issuer_name, confidence) from the first plausible header line.

        Scans the first 10 non-empty lines.  A line is accepted only when ALL
        of the following pass:
          1. len >= 8
          2. at least 4 alphabetic characters
          3. (alnum + space) ratio >= 0.55
          4. does not start with a known skip prefix
          5. does not contain © ® ™
          6. does not contain Unicode bidi direction markers
          7. does not start with a digit
          8. does not look like a pure date (DD/MM/YYYY)
          9. does not look like a pure phone number

        Confidence:
          0.75  — ALL CAPS and len >= 10  (company letterheads)
          0.65  — mixed case and len >= 10
          0.55  — anything shorter that still passes
        """
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

        for line in lines[:10]:
            # Rule 1: minimum length
            if len(line) < 8:
                continue
            # Rule 2: at least 4 actual letters
            if sum(c.isalpha() for c in line) < 4:
                continue
            # Rule 3: (alnum + space) ratio
            ratio = sum(c.isalnum() or c.isspace() for c in line) / len(line)
            if ratio < 0.55:
                continue
            # Rule 5: copyright / trademark symbols
            if '©' in line or '®' in line or '™' in line:
                continue
            # Rule 6: bidi direction markers from mixed Arabic/French OCR
            if any(c in line for c in ('‎', '‏', '‪', '‫', '‬', '‭', '‮')):
                continue
            # Rule 7: company names never start with a digit
            if line[0].isdigit():
                continue
            # Rule 8: pure date pattern
            if re.match(r'^\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4}$', line):
                continue
            # Rule 9: pure phone number
            if re.match(r'^\+?[\d\s\-\.()]{7,}$', line):
                continue
            lower = line.lower()
            # Rule 4a: exact keyword match
            if lower in self._SKIP_EXACT:
                continue
            # Rule 4b: starts with a known skip prefix
            if any(lower.startswith(p) for p in self._SKIP_PREFIXES):
                continue
            # Street address: digits then road-type word
            if re.match(r'^\d+\s+(?:rue|avenue|zone|bp|all[eé]e|boulevard|impasse)',
                        lower):
                continue

            # Passed all rules — compute confidence
            if line.isupper() and len(line) >= 10:
                conf = 0.75
            elif len(line) >= 10:
                conf = 0.65
            else:
                conf = 0.55
            return line, conf

        return None, 0.0

    # ── Invoice number ────────────────────────────────────────────────────────

    def _extract_invoice_number(self, text: str) -> str | None:
        """Try each pattern in order; return the first match.

        Confidence when used: 0.85.
        """
        logger.debug("header_raw_text_sample",
                     text_sample=text[:500].replace("\n", " | "))

        for pattern in self._INV_PATTERNS:
            m = re.search(pattern, text)
            if m:
                result = m.group(1) if m.lastindex else m.group(0)
                result = result.strip().rstrip('.,;:')
                if len(result) >= 4:
                    return result
        return None

    # ── Invoice date ──────────────────────────────────────────────────────────

    def _extract_date(self, text: str) -> date | None:
        """Return the invoice issue date (not the due date).

        Priority:
          1. Labelled "Date de facture" / "Date d'émission" line → DD/MM/YYYY
          2. Any DD/MM/YYYY (or DD-MM-YYYY or DD.MM.YYYY) in the first 20 lines
          3. ISO YYYY-MM-DD
          4. French textual date "15 juin 2026"
        Dates with year < 2020 or > 2030 are rejected.
        Confidence when used: 0.90.
        """
        lines = text.split("\n")

        # Pass 1: prefer labelled invoice-date lines
        invoice_date_re = re.compile(
            r"(?:date\s+de\s+facture|date\s+d.?[eé]mission|date\s+facture)\s*:?\s*"
            r"(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4})",
            re.IGNORECASE,
        )
        for line in lines[:30]:
            m = invoice_date_re.search(line)
            if m:
                d = self._parse_dmy(m.group(1))
                if d:
                    return d

        # Pass 2: first DD/MM/YYYY in early lines (skip due-date lines)
        dmy_re = re.compile(r'\b(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4})\b')
        for line in lines[:20]:
            lower = line.lower()
            if any(kw in lower for kw in ("échéance", "echeance", "due date", "paiement")):
                continue
            m = dmy_re.search(line)
            if m:
                d = self._parse_dmy(m.group(1))
                if d:
                    return d

        # Pass 3: ISO YYYY-MM-DD
        iso_re = re.compile(r'\b(\d{4}-\d{2}-\d{2})\b')
        for line in lines[:20]:
            m = iso_re.search(line)
            if m:
                try:
                    parts = m.group(1).split('-')
                    d = date(int(parts[0]), int(parts[1]), int(parts[2]))
                    if self._valid_year(d.year):
                        return d
                except (ValueError, IndexError):
                    pass

        # Pass 4: French text "15 juin 2026"
        fr_re = re.compile(
            r'\b(\d{1,2})\s+([a-zéàûîôùèâ]+)\s+(\d{4})\b',
            re.IGNORECASE,
        )
        for line in lines[:20]:
            m = fr_re.search(line)
            if m:
                try:
                    day   = int(m.group(1))
                    month = self._MONTHS_FR.get(m.group(2).lower())
                    year  = int(m.group(3))
                    if month and self._valid_year(year) and 1 <= day <= 31:
                        return date(year, month, day)
                except (ValueError, TypeError):
                    pass

        return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _valid_year(year: int) -> bool:
        return 2020 <= year <= 2030

    def _parse_dmy(self, raw: str) -> date | None:
        """Parse DD/MM/YYYY, DD-MM-YYYY, or DD.MM.YYYY."""
        sep = re.search(r'[/.\-]', raw)
        if not sep:
            return None
        parts = re.split(r'[/.\-]', raw)
        if len(parts) != 3:
            return None
        try:
            if len(parts[0]) == 4:
                year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
            else:
                day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            if not self._valid_year(year):
                return None
            if not (1 <= month <= 12 and 1 <= day <= 31):
                return None
            return date(year, month, day)
        except (ValueError, TypeError):
            return None
