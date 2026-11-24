from conftest import full_assessment

from rfp_agent.schemas import Assessment
from rfp_agent.scoring import score_assessment


def test_weighted_score_rounds_half_up():
    result = score_assessment(full_assessment())
    assert result["fit_score_raw"] == 7.4
    assert result["fit_score"] == 7
    assert result["decision"] == "BID"


def test_low_scope_caps_score_and_forces_no_bid():
    assessment = full_assessment()
    assessment.fit_factors[0].score = 2
    result = score_assessment(assessment)
    assert result["fit_score"] <= 2
    assert result["decision"] == "NO_BID"
    assert result["guardrail_notes"]


def test_failed_gate_forces_no_bid():
    assessment = full_assessment()
    assessment.gates[0].status = "FAIL"
    result = score_assessment(assessment)
    assert result["decision"] == "NO_BID"
    assert "gate-001" in result["guardrail_notes"][0]


def test_inconsistent_bid_warns_without_override():
    assessment = Assessment.model_validate(
        {
            "gates": [],
            "fit_factors": [
                {"factor": "scope_fit", "score": 3, "reason": "Partial."},
                {"factor": "eligibility", "score": 0, "reason": "Unknown."},
                {"factor": "delivery_feasibility", "score": 0, "reason": "Risky."},
                {"factor": "commercial_risk", "score": 0, "reason": "Poor."},
            ],
            "decision": "BID",
            "reasons": ["One", "Two", "Three"],
            "deal_breakers": [],
            "what_would_change_my_mind": [],
            "open_questions_for_agency": [],
        }
    )
    result = score_assessment(assessment)
    assert result["decision"] == "BID"
    assert result["warnings"]


def test_inconsistent_high_score_no_bid_warns_without_override():
    assessment = full_assessment()
    assessment.decision = "NO_BID"
    for factor in assessment.fit_factors:
        factor.score = 9
    result = score_assessment(assessment)
    assert result["decision"] == "NO_BID"
    assert result["fit_score"] == 9
    assert result["warnings"]
