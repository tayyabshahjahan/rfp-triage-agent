"""Assemble and validate the final public report JSON."""

from __future__ import annotations

from datetime import date

from .dates import validate_dates
from .prompts import PROMPT_VERSION
from .radar import build_calendar, build_radar
from .schemas import Assessment, Extraction, FinalReport, VerificationSummary
from .scoring import score_assessment


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
) -> FinalReport:
    date_warnings = validate_dates(extraction.dates, as_of)
    score = score_assessment(assessment)
    radar_rows = build_radar(extraction, assessment, as_of)
    calendar = build_calendar(extraction, radar_rows, as_of)
    warnings = [*date_warnings, *score["warnings"]]  # type: ignore[list-item]

    return FinalReport(
        decision=score["decision"],  # type: ignore[arg-type]
        fit_score=score["fit_score"],  # type: ignore[arg-type]
        deadlines=[item.model_dump(mode="json") for item in extraction.dates],
        requirements=[item.model_dump(mode="json") for item in extraction.requirements],
        reasons=assessment.reasons,
        summary=extraction.summary,
        facts=extraction.facts.model_dump(mode="json"),
        fit_factors=[item.model_dump(mode="json") for item in assessment.fit_factors],
        fit_score_raw=score["fit_score_raw"],  # type: ignore[arg-type]
        deal_breakers=assessment.deal_breakers,
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
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "seconds": round(seconds, 2),
            "as_of": as_of.isoformat(),
        },
    )
