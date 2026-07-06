"""Génération séquentielle des numéros de factures émises par BIAT IT.

Format : FAC-IT-{ANNÉE}-{SÉQUENCE:04d}
Exemple : FAC-IT-2026-0001
"""
from __future__ import annotations

import re
from datetime import date


_PATTERN = re.compile(r"^FAC-IT-(\d{4})-(\d+)$")


class InvoiceNumberer:
    """Génère des numéros de factures séquentiels en interrogeant le dépôt."""

    def __init__(self, repository) -> None:
        self._repo = repository

    def next_number(self, invoice_date: date | None = None) -> str:
        year = (invoice_date or date.today()).year
        last_seq = self._repo.get_max_sequence(year)
        return f"FAC-IT-{year}-{last_seq + 1:04d}"

    @staticmethod
    def parse_sequence(invoice_number: str) -> tuple[int, int] | None:
        """Extraire (année, séquence) d'un numéro FAC-IT-YYYY-NNNN.

        Returns None if the number does not match the expected format.
        """
        m = _PATTERN.match(invoice_number)
        if not m:
            return None
        return int(m.group(1)), int(m.group(2))
