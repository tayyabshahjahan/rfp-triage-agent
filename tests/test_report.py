from datetime import date

from conftest import extraction_fixture, full_assessment

from rfp_agent.report import build_report
from rfp_agent.schemas import Evidence, VerificationSummary


def test_guardrail_override_aligns_reasons_and_conditional_deal_breakers():
    extraction = extraction_fixture()
    gate = extraction.gate_candidates[0]
    gate.consequence = "Proposals that do not comply will be rejected."
    gate.consequence_evidence = Evidence(
        quote="Proposals that do not comply will be rejected.",
        page=1,
        verified=True,
        match="exact",
    )
    assessment = full_assessment()
    assessment.decision = "NO_BID"

    report = build_report(
        extraction=extraction,
        assessment=assessment,
        verification=VerificationSummary(total_items=1, verified=1, unverified=0),
        file_name="fixture.pdf",
        page_count=1,
        model="fake",
        seconds=1.0,
        as_of=date(2026, 11, 25),
    )

    assert report.decision == "BID"
    assert report.model_decision == "NO_BID"
    assert report.reasons[0].startswith("scope_fit (9/10)")
    assert any(reason.startswith("Conditional BID:") for reason in report.reasons)
    assert any(
        item.startswith("Would be a deal-breaker if unmet:")
        for item in report.deal_breakers
    )
