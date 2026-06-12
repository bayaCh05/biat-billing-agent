from __future__ import annotations

import re
from datetime import date

FRENCH_MONTHS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
}

ARABIC_MONTHS = {
    "يناير": 1, "فبراير": 2, "مارس": 3, "أبريل": 4, "ابريل": 4,
    "مايو": 5, "يونيو": 6, "يوليو": 7, "أغسطس": 8, "اغسطس": 8,
    "سبتمبر": 9, "أكتوبر": 10, "اكتوبر": 10, "نوفمبر": 11, "ديسمبر": 12,
}

_DMY = re.compile(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})")
_DIGITS_YEAR = re.compile(r"(\d{1,2})\D+(\d{4})")


def parse_date(raw: str | None) -> date | None:
    """Parse a date string in several formats. Returns None on failure.

    Handled formats:
      ISO 8601: 2024-06-01
      DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
      French textual: "1er juin 2024", "15 mars 2024"
      Arabic textual: "1 يناير 2024"
    """
    if not raw:
        return None
    raw = raw.strip()

    # ISO 8601 — most likely from LLM output
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        pass

    # DD/MM/YYYY or variants
    m = _DMY.match(raw)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass

    raw_lower = raw.lower()

    # French month name
    for name, month_num in FRENCH_MONTHS.items():
        if name in raw_lower:
            digits = _DIGITS_YEAR.search(raw_lower)
            if digits:
                try:
                    return date(int(digits.group(2)), month_num, int(digits.group(1)))
                except ValueError:
                    pass

    # Arabic month name
    for name, month_num in ARABIC_MONTHS.items():
        if name in raw:
            digits = re.search(r"(\d{1,2})\D+(\d{4})", raw)
            if digits:
                try:
                    return date(int(digits.group(2)), month_num, int(digits.group(1)))
                except ValueError:
                    pass

    return None
