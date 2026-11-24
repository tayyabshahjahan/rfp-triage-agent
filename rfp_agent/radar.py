"""Disqualification radar rows and merged do-by calendar."""

from __future__ import annotations

from datetime import date

from .schemas import Assessment, Extraction


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
        days, timing = _date_status(candidate.action_date, as_of)
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
                "action_date": candidate.action_date,
                "days_remaining": days,
                "timing": timing,
                "consequence": candidate.consequence,
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
