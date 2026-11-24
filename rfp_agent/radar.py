"""Disqualification radar rows and merged do-by calendar."""

from __future__ import annotations

from datetime import date

from dateutil import parser

from .schemas import Assessment, Extraction

_PROPOSAL_GATED_TYPES = {
    "REGISTRATION_OR_CERT",
    "BONDS_AND_INSURANCE",
    "SUBMISSION_RULES",
    "FORMAT_AND_FORMS",
    "ADDENDUM_ACK",
}


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


def _deadline(extraction: Extraction, kind: str) -> str | None:
    for item in extraction.dates:
        if item.kind == kind:
            return _iso_date(item.date)
    return None


def _is_rsvp(candidate: object) -> bool:
    text = " ".join(
        str(getattr(candidate, field, ""))
        for field in ("title", "requirement", "action")
    ).casefold()
    return "rsvp" in text or "email by" in text


def _rsvp_date(extraction: Extraction, action_date: str | None) -> str | None:
    for item in extraction.dates:
        text = f"{item.what} {item.date_text} {item.evidence.quote}".casefold()
        if "rsvp" in text or "email by" in text:
            return _iso_date(item.date)
    return _iso_date(action_date)


def _gate_action_date(candidate: object, extraction: Extraction) -> str | None:
    if _is_rsvp(candidate):
        return _rsvp_date(extraction, getattr(candidate, "action_date", None))
    if getattr(candidate, "needs_agency_answer", False):
        return _deadline(extraction, "QUESTIONS_DUE")
    if getattr(candidate, "type", None) in _PROPOSAL_GATED_TYPES:
        return _deadline(extraction, "PROPOSAL_DUE")
    return _iso_date(getattr(candidate, "action_date", None))


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
        action_date = _gate_action_date(candidate, extraction)
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
    for item in extraction.dates:
        events.append(
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
        events.append(
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
