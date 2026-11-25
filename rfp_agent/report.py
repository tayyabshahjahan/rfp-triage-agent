"""Assemble and validate the final public report JSON."""

from __future__ import annotations

from datetime import date

from .dates import validate_dates
from .prompts import PROMPT_VERSION
from .radar import build_calendar, build_radar
from .schemas import Assessment, Extraction, FinalReport, VerificationSummary
from .scoring import score_assessment


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = " ".join(value.casefold().split())
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _decision_reasons(
    assessment: Assessment,
    decision: str,
    radar_rows: list[dict[str, object]],
) -> list[str]:
    if decision == assessment.decision:
        return assessment.reasons

    reverse = decision == "BID"
    factors = sorted(assessment.fit_factors, key=lambda item: item.score, reverse=reverse)
    reasons: list[str] = []
    if factors:
        factor = factors.pop(0)
        reasons.append(f"{factor.factor} ({factor.score}/10): {factor.reason}")

    relevant_status = "UNKNOWN" if decision == "BID" else "FAIL"
    gates = [row for row in radar_rows if row["status"] == relevant_status]
    if gates:
        gate = gates[0]
        prefix = "Conditional BID" if decision == "BID" else "Confirmed blocker"
        reasons.append(f"{prefix}: {gate['requirement']} Consequence: {gate['consequence']}")

    for factor in factors:
        reasons.append(f"{factor.factor} ({factor.score}/10): {factor.reason}")
        if len(reasons) == 3:
            break
    for original in assessment.reasons:
        reasons.append(original)
        if len(_unique(reasons)) >= 3:
            break
    return _unique(reasons)[:3]


def _deal_breakers(
    assessment: Assessment, radar_rows: list[dict[str, object]]
) -> list[str]:
    values = list(assessment.deal_breakers)
    rejection_terms = ("reject", "disqual", "not be evaluated", "ineligible", "nonresponsive")
    for row in radar_rows:
        if row["status"] == "FAIL":
            values.append(f"Confirmed blocker: {row['title']} - {row['requirement']}")
            continue
        consequence = str(row["consequence"])
        if row["status"] == "UNKNOWN" and any(
            term in consequence.casefold() for term in rejection_terms
        ):
            values.append(
                f"Would be a deal-breaker if unmet: {row['title']} - {row['requirement']}"
            )
    return _unique(values)


def build_report(
    *,
    extraction: Extraction,
    assessment: Assessment,
    verification: VerificationSummary,
    file_name: str,
    page_count: int,
    model: str,
    seconds: float,
    as_of: date,
    pages: list[str] | None = None,
    score_result: dict[str, object] | None = None,
    llm_calls: list[dict[str, object]] | None = None,
) -> FinalReport:
    date_warnings = validate_dates(extraction.dates, as_of, pages)
    score = score_result or score_assessment(assessment, extraction.gate_candidates)
    radar_rows = build_radar(extraction, assessment, as_of)
    calendar = build_calendar(extraction, radar_rows, as_of)
    warnings = [*date_warnings, *score["warnings"]]  # type: ignore[list-item]
    calls = llm_calls or []
    answering_call = calls[-1] if calls else {}

    return FinalReport(
        decision=score["decision"],  # type: ignore[arg-type]
        model_decision=score["model_decision"],  # type: ignore[arg-type]
        fit_score=score["fit_score"],  # type: ignore[arg-type]
        deadlines=[item.model_dump(mode="json") for item in extraction.dates],
        requirements=[item.model_dump(mode="json") for item in extraction.requirements],
        reasons=_decision_reasons(assessment, str(score["decision"]), radar_rows),
        summary=extraction.summary,
        facts=extraction.facts.model_dump(mode="json"),
        fit_factors=[item.model_dump(mode="json") for item in assessment.fit_factors],
        fit_score_raw=score["fit_score_raw"],  # type: ignore[arg-type]
        deal_breakers=_deal_breakers(assessment, radar_rows),
        what_would_change_my_mind=assessment.what_would_change_my_mind,
        open_questions_for_agency=assessment.open_questions_for_agency,
        ambiguities=[item.model_dump(mode="json") for item in extraction.ambiguities],
        gates=radar_rows,
        calendar=calendar,
        verification=verification.model_dump(mode="json", exclude={"failing_ids"}),
        guardrail_notes=score["guardrail_notes"],  # type: ignore[arg-type]
        warnings=warnings,
        meta={
            "file_name": file_name,
            "pages": page_count,
            "provider": answering_call.get("provider"),
            "model": answering_call.get("model", model),
            "retries": sum(int(call.get("retries", 0)) for call in calls),
            "llm_calls": calls,
            "prompt_version": PROMPT_VERSION,
            "seconds": round(seconds, 2),
            "as_of": as_of.isoformat(),
        },
    )
