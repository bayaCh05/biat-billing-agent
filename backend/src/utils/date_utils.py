"""Date utility helpers shared across budget and capex modules."""
from __future__ import annotations

import calendar
import datetime


def last_day_of_month(year: int, month: int) -> datetime.date:
    """Return the last calendar day of the given month as a date object."""
    if month == 12:
        return datetime.date(year, 12, 31)
    return datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)


def last_day_int(year: int, month: int) -> int:
    """Return the last day-of-month as an integer (e.g. 28, 29, 30, or 31)."""
    return calendar.monthrange(year, month)[1]
