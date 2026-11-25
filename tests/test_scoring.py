from conftest import extraction_fixture, full_assessment

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


def test_score_six_with_all_unknown_gates_is_bid():
    assessment = full_assessment()
    assessment.decision = "NO_BID"
    for factor in assessment.fit_factors:
        factor.score = 6
    result = score_assessment(assessment)
    assert result["decision"] == "BID"
    assert result["fit_score"] == 6
    assert result["model_decision"] == "NO_BID"
    assert result["guardrail_notes"]


def test_score_four_is_no_bid():
    assessment = full_assessment()
    assessment.decision = "BID"
    for factor in assessment.fit_factors:
        factor.score = 4
    result = score_assessment(assessment)
    assert result["decision"] == "NO_BID"
    assert result["fit_score"] == 4
    assert result["model_decision"] == "BID"


def test_profile_dependent_pass_gate_is_changed_to_unknown():
    extraction = extraction_fixture()
    extraction.gate_candidates[0].gate_id = "gate-001"
    assessment = full_assessment()
    assessment.gates[0].status = "PASS"

    result = score_assessment(assessment, extraction.gate_candidates)

    assert assessment.gates[0].status == "UNKNOWN"
    assert "unconfirmed" in assessment.gates[0].status_reason
    assert any("PASS to UNKNOWN" in note for note in result["guardrail_notes"])
