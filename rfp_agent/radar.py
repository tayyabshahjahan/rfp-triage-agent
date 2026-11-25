"""Disqualification radar rows and merged do-by calendar."""

from __future__ import annotations

import re
from datetime import date, datetime

from dateutil import parser

from .schemas import Assessment, Extraction, GateCandidate

_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUMERIC_DATE = re.compile(r"\b\d{1,2}/\d{1,2}/(?:\d{2}|\d{4})\b")
_MONTH_DATE = re.compile(
    r"(?i)\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+(?:19|20)\d{2})?\b"
)


def _topic_key(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    text = re.sub(r"^action\s+", "", text)
    text = re.sub(r"^minimum qualification\s+\d+\s+", "", text)
    if "notice of intent" in text or re.search(r"\bnip\b", text):
        return "notice of intent to propose"
    if "communication" in text or "procurement contact" in text:
        return "communication restriction"
    if "bid security" in text:
        return "bid security"
    if "notarized" in text and "attachment" in text:
        return "notarized attachment"
    return text


def _dedupe_radar_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    status_order = {"FAIL": 0, "UNKNOWN": 1, "PASS": 2}
    unique: list[dict[str, object]] = []
    by_topic: dict[str, dict[str, object]] = {}
    for row in rows:
        topic = _topic_key(f"{row['title']} {row['requirement']}")
        existing = by_topic.get(topic)
        if existing is None:
            by_topic[topic] = row
            unique.append(row)
            continue

        if status_order[str(row["status"])] < status_order[str(existing["status"])]:
            existing["status"] = row["status"]
            existing["status_reason"] = row["status_reason"]
            existing["suggested_question"] = row["suggested_question"]
        if existing["action_date"] is None and row["action_date"] is not None:
            existing["action_date"] = row["action_date"]
            existing["days_remaining"] = row["days_remaining"]
            existing["timing"] = row["timing"]
        if existing["consequence"] == "Not stated" and row["consequence"] != "Not stated":
            existing["consequence"] = row["consequence"]
            existing["consequence_evidence"] = row["consequence_evidence"]
    return unique


def _iso_date(value: object | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        try:
            return parser.parse(text).date().isoformat()
        except (OverflowError, ValueError):
            return None


def _dates_named_in(text: str, default_year: int | None) -> list[str]:
    matches = [*_ISO_DATE.findall(text), *_NUMERIC_DATE.findall(text)]
    matches.extend(_MONTH_DATE.findall(text))
    dates: list[str] = []
    for match in matches:
        cleaned = re.sub(r"(?i)(\d)(st|nd|rd|th)\b", r"\1", match)
        has_year = bool(re.search(r"\b(?:19|20)\d{2}\b", cleaned))
        if not has_year and default_year is None:
            continue
        try:
            default = datetime(default_year or 2000, 1, 1)
            normalized = parser.parse(cleaned, default=default).date().isoformat()
        except (OverflowError, ValueError):
            continue
        if normalized not in dates:
            dates.append(normalized)
    return dates


def _gate_action_date(candidate: GateCandidate) -> str | None:
    proposed = _iso_date(candidate.action_date)
    default_year = date.fromisoformat(proposed).year if proposed else None
    named_dates: list[str] = []
    for text in (candidate.requirement, candidate.evidence.quote):
        for named_date in _dates_named_in(text, default_year):
            if named_date not in named_dates:
                named_dates.append(named_date)
    if proposed in named_dates:
        return proposed
    return named_dates[0] if named_dates else None


def _date_status(value: str | None, as_of: date) -> tuple[int | None, str | None]:
    if not value:
        return None, None
    try:
        days = (date.fromisoformat(value) - as_of).days
    except ValueError:
        return None, None
    return days, "PASSED" if days < 0 else "TODAY" if days == 0 else "UPCOMING"


def build_radar(
    extraction: Extraction, assessment: Assessment, as_of: date
) -> list[dict[str, object]]:
    assessed = {gate.gate_id: gate for gate in assessment.gates}
    rows: list[dict[str, object]] = []
    for candidate in extraction.gate_candidates:
        result = assessed.get(candidate.gate_id)
        status = result.status if result else "UNKNOWN"
        reason = (
            result.status_reason
            if result
            else "The gate was not assessed, so compliance must be confirmed."
        )
        suggested_question = None
        if status == "UNKNOWN":
            suggested_question = (
                "Please confirm how bidders should demonstrate compliance with this requirement: "
                f"{candidate.requirement}"
            )
        action_date = _gate_action_date(candidate)
        consequence_evidence = candidate.consequence_evidence
        consequence_verified = bool(
            consequence_evidence is not None and consequence_evidence.verified
        )
        days, timing = _date_status(action_date, as_of)
        rows.append(
            {
                "gate_id": candidate.gate_id,
                "status": status,
                "type": candidate.type,
                "title": candidate.title,
                "requirement": candidate.requirement,
                "status_reason": reason,
                "suggested_question": suggested_question,
                "action": candidate.action,
                "action_date": action_date,
                "days_remaining": days,
                "timing": timing,
                "consequence": candidate.consequence if consequence_verified else "Not stated",
                "consequence_evidence": (
                    consequence_evidence.model_dump(mode="json")
                    if consequence_verified and consequence_evidence is not None
                    else None
                ),
                "evidence": candidate.evidence.model_dump(mode="json"),
            }
        )

    rows = _dedupe_radar_rows(rows)
    status_order = {"FAIL": 0, "UNKNOWN": 1, "PASS": 2}
    rows.sort(
        key=lambda row: (
            status_order[str(row["status"])],
            row["action_date"] is None,
            row["action_date"] or "9999-12-31",
            str(row["title"]),
        )
    )
    return rows


def build_calendar(
    extraction: Extraction, radar_rows: list[dict[str, object]], as_of: date
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    by_key: dict[tuple[str, str], dict[str, object]] = {}

    def add_event(event: dict[str, object]) -> None:
        key = (str(event["date"]), _topic_key(str(event["title"])))
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = event
            events.append(event)
            return
        if existing.get("time") is None and event.get("time") is not None:
            existing["time"] = event["time"]
            existing["timezone"] = event["timezone"]
        if existing["source"] == "gate" and event["source"] == "deadline":
            existing.update(event)

    for item in extraction.dates:
        add_event(
            {
                "title": item.what,
                "date": item.date,
                "time": item.time,
                "timezone": item.timezone,
                "source": "deadline",
                "kind": item.kind,
                "days_remaining": item.days_remaining,
                "timing": item.timing,
                "evidence": item.evidence.model_dump(mode="json"),
            }
        )
    for row in radar_rows:
        if not row["action_date"]:
            continue
        days, timing = _date_status(str(row["action_date"]), as_of)
        add_event(
            {
                "title": f"Action: {row['title']}",
                "date": row["action_date"],
                "time": None,
                "timezone": None,
                "source": "gate",
                "kind": row["type"],
                "days_remaining": days,
                "timing": timing,
                "evidence": row["evidence"],
            }
        )
    events.sort(key=lambda item: (str(item["date"]), str(item["time"] or ""), str(item["title"])))
    return events
