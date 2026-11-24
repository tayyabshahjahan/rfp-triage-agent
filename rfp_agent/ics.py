"""Small RFC 5545 calendar writer with UTF-8 line folding."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def _fold(line: str) -> list[str]:
    lines: list[str] = []
    current = ""
    for character in line:
        if len((current + character).encode("utf-8")) > 75:
            lines.append(current)
            current = " " + character
        else:
            current += character
    lines.append(current)
    return lines


def _event_lines(event: dict[str, object], stamp: datetime) -> list[str]:
    event_date = date.fromisoformat(str(event["date"]))
    event_time = event.get("time")
    uid_source = f"{event.get('source')}|{event.get('title')}|{event_date}|{event_time}"
    uid = hashlib.sha256(uid_source.encode()).hexdigest()[:24] + "@rfp-triage-agent"
    evidence = event.get("evidence") or {}
    quote = str(evidence.get("quote", "")) if isinstance(evidence, dict) else ""
    page = str(evidence.get("page", "")) if isinstance(evidence, dict) else ""
    description = f"Evidence: {quote} (page {page})" if quote else "Evidence: Not stated"

    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        f"SUMMARY:{_escape(str(event['title']))}",
        f"DESCRIPTION:{_escape(description)}",
    ]
    if event_time:
        local_time = time.fromisoformat(str(event_time))
        naive = datetime.combine(event_date, local_time)
        timezone_name = event.get("timezone")
        if timezone_name:
            try:
                start = naive.replace(tzinfo=ZoneInfo(str(timezone_name))).astimezone(UTC)
                lines.append(f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}")
            except ZoneInfoNotFoundError:
                lines.append(f"DTSTART:{naive.strftime('%Y%m%dT%H%M%S')}")
        else:
            lines.append(f"DTSTART:{naive.strftime('%Y%m%dT%H%M%S')}")
    else:
        lines.extend(
            [
                f"DTSTART;VALUE=DATE:{event_date.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{(event_date + timedelta(days=1)).strftime('%Y%m%d')}",
            ]
        )
    lines.extend(
        [
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            "DESCRIPTION:RFP action due tomorrow",
            "TRIGGER:-P1D",
            "END:VALARM",
            "END:VEVENT",
        ]
    )
    return lines


def build_ics(events: list[dict[str, object]], *, now: datetime | None = None) -> bytes:
    stamp = now or datetime.now(UTC)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//idiaz.io//RFP Triage Agent//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for event in events:
        lines.extend(_event_lines(event, stamp))
    lines.append("END:VCALENDAR")
    folded = [part for line in lines for part in _fold(line)]
    return ("\r\n".join(folded) + "\r\n").encode("utf-8")
