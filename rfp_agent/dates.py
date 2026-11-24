"""Deterministic date checks and as-of calculations."""

from __future__ import annotations

from datetime import date

from dateutil import parser

from .schemas import DateItem


def check_date(item: DateItem) -> str | None:
    try:
        parsed = parser.parse(item.date_text, fuzzy=True).date()
        expected = date.fromisoformat(item.date)
    except (ValueError, OverflowError):
        item.date_check = "unparseable"
        return f"Could not verify the parsed date for {item.what!r}."
    if parsed != expected:
        item.date_check = "mismatch"
        return (
            f"Date mismatch for {item.what!r}: document text {item.date_text!r} "
            f"does not match {item.date}."
        )
    item.date_check = "ok"
    return None


def add_as_of(item: DateItem, as_of: date) -> None:
    try:
        event_date = date.fromisoformat(item.date)
    except ValueError:
        return
    item.days_remaining = (event_date - as_of).days
    if item.days_remaining < 0:
        item.timing = "PASSED"
    elif item.days_remaining == 0:
        item.timing = "TODAY"
    else:
        item.timing = "UPCOMING"


def validate_dates(items: list[DateItem], as_of: date) -> list[str]:
    warnings: list[str] = []
    for item in items:
        warning = check_date(item)
        if warning:
            warnings.append(warning)
        add_as_of(item, as_of)
    return warnings
