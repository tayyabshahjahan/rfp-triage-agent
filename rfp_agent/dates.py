"""Deterministic date checks and as-of calculations."""

from __future__ import annotations

import re
from datetime import date

from dateutil import parser

from .schemas import DateItem

_TIME_WITH_MINUTES = re.compile(
    r"(?i)\b(\d{1,2}):(\d{2})(?::\d{2})?\s*(AM|PM)?\b"
)
_TIME_WITH_MERIDIEM = re.compile(r"(?i)\b(\d{1,2})\s*(AM|PM)\b")
_TIMEZONE_ALIASES = (
    (
        re.compile(r"(?i)\b(?:PT|PST|PDT|PACIFIC(?:\s+(?:STANDARD|DAYLIGHT))?\s+TIME|PACIFIC)\b"),
        "America/Los_Angeles",
    ),
    (
        re.compile(r"(?i)\b(?:ET|EST|EDT|EASTERN(?:\s+(?:STANDARD|DAYLIGHT))?\s+TIME|EASTERN)\b"),
        "America/New_York",
    ),
    (
        re.compile(r"(?i)\b(?:CT|CST|CDT|CENTRAL(?:\s+(?:STANDARD|DAYLIGHT))?\s+TIME|CENTRAL)\b"),
        "America/Chicago",
    ),
    (
        re.compile(r"(?i)\b(?:MT|MST|MDT|MOUNTAIN(?:\s+(?:STANDARD|DAYLIGHT))?\s+TIME|MOUNTAIN)\b"),
        "America/Denver",
    ),
)


def normalize_time(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().replace(".", "")
    if not text:
        return None
    if text.casefold() == "noon":
        return "12:00"
    if text.casefold() == "midnight":
        return "00:00"

    match = _TIME_WITH_MINUTES.search(text) or _TIME_WITH_MERIDIEM.search(text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2)) if match.re is _TIME_WITH_MINUTES else 0
    meridiem = match.group(3) if match.re is _TIME_WITH_MINUTES else match.group(2)
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem.upper() == "PM" else 0)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def normalize_timezone(value: object | None, *hints: object | None) -> str | None:
    candidates = [str(item).strip() for item in (value, *hints) if item]
    for candidate in candidates:
        iana = re.search(r"\b[A-Za-z]+/[A-Za-z_+-]+\b", candidate)
        if iana:
            return iana.group()
    combined = " ".join(candidates)
    for pattern, timezone_name in _TIMEZONE_ALIASES:
        if pattern.search(combined):
            return timezone_name
    return None


def infer_page_timezone(page_text: str | None) -> str | None:
    if not page_text:
        return None
    found: set[str] = set()
    for raw_line in page_text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not re.search(r"(?i)\b(?:date(?:s| and time)?|all times?|time zone)\b", line):
            continue
        timezone_name = normalize_timezone(line)
        if timezone_name:
            found.add(timezone_name)
    return next(iter(found)) if len(found) == 1 else None


def normalize_date_time(item: DateItem, page_text: str | None = None) -> None:
    source_time = item.time or item.date_text
    item.time = normalize_time(source_time)
    item.timezone = normalize_timezone(item.timezone, source_time, item.date_text)
    if item.time is not None and item.timezone is None:
        item.timezone = infer_page_timezone(page_text)


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


def validate_dates(
    items: list[DateItem], as_of: date, pages: list[str] | None = None
) -> list[str]:
    warnings: list[str] = []
    for item in items:
        page_text = None
        if pages is not None and 1 <= item.evidence.page <= len(pages):
            page_text = pages[item.evidence.page - 1]
        normalize_date_time(item, page_text)
        warning = check_date(item)
        if warning:
            warnings.append(warning)
        add_as_of(item, as_of)
    return warnings
