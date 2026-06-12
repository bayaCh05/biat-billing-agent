"""Rules-based extraction of issuer_name, invoice_number, invoice_date from raw text.

Runs BEFORE the LLM call so these three fields are available even in
amounts_only mode where the LLM only handles monetary totals.
"""
from __future__ import annotations

import re
from datetime import date


class HeaderExtractor:
    """Heuristic extraction of three header fields from Tunisian invoice text."""

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
    )
    _SKIP_EXACT = frozenset({
        "facture", "fournisseur", "client", "devise",
        "ht", "tva", "ttc", "invoice",
    })

    def extract(self, text: str) -> dict:
        return {
            'issuer_name':    self._extract_issuer(text),
            'invoice_number': self._extract_invoice_number(text),
            'invoice_date':   self._extract_date(text),
        }

    # ── Issuer name ───────────────────────────────────────────────────────────

    def _extract_issuer(self, text: str) -> str | None:
        """Return the first line that looks like a company name.

        Heuristic: scan the first 8 non-empty lines; return the first that:
          - Is at least 4 characters long
          - Does not start with any of the skip prefixes
          - Is not an exact match for a common keyword
          - Does not look like a street address (digits + Rue / Avenue / Zone)
        Confidence when used: 0.70.
        """
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

        for line in lines[:8]:
            if len(line) < 4:
                continue
            lower = line.lower()
            if lower in self._SKIP_EXACT:
                continue
            if any(lower.startswith(p) for p in self._SKIP_PREFIXES):
                continue
            # Street address pattern: starts with digits followed by Rue/Avenue/Zone/BP
            if re.match(r'^\d+\s+(?:rue|avenue|zone|bp|all[eé]e|boulevard|impasse)',
                        lower):
                continue
            # Pure digits or very short codes
            if re.match(r'^[\d\s\-/.,]+$', line):
                continue
            return line
        return None

    # ── Invoice number ────────────────────────────────────────────────────────

    def _extract_invoice_number(self, text: str) -> str | None:
        """Try each pattern in order; return the first match.

        Confidence when used: 0.85.
        """
        for pattern in self._INV_PATTERNS:
            m = re.search(pattern, text)
            if m:
                # Named group or first capture group
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
            # Skip lines that are clearly about the due date
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
            # Determine if first chunk is day or year (YYYY-MM-DD vs DD/MM/YYYY)
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
