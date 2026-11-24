from datetime import date

from conftest import extraction_fixture, full_assessment

from rfp_agent.radar import build_radar


def test_radar_sorts_fail_then_unknown_then_pass():
    extraction = extraction_fixture()
    original = extraction.gate_candidates[0]
    extraction.gate_candidates = [
        original.model_copy(update={"gate_id": "gate-002", "title": "Unknown gate"}),
        original.model_copy(update={"gate_id": "gate-001", "title": "Failed gate"}),
        original.model_copy(update={"gate_id": "gate-003", "title": "Passed gate"}),
    ]
    assessment = full_assessment()
    assessment.gates = [
        assessment.gates[0].model_copy(update={"gate_id": "gate-001", "status": "FAIL"}),
        assessment.gates[0].model_copy(update={"gate_id": "gate-002", "status": "UNKNOWN"}),
        assessment.gates[0].model_copy(update={"gate_id": "gate-003", "status": "PASS"}),
    ]
    rows = build_radar(extraction, assessment, date(2027, 1, 1))
    assert [row["status"] for row in rows] == ["FAIL", "UNKNOWN", "PASS"]
    assert rows[1]["suggested_question"]
