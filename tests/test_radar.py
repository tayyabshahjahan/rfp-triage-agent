from datetime import date

from conftest import extraction_fixture, full_assessment

from rfp_agent.radar import build_radar
from rfp_agent.schemas import Evidence


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


def test_radar_assigns_proposal_question_and_rsvp_dates():
    extraction = extraction_fixture()
    extraction.dates.append(
        extraction.dates[0].model_copy(
            update={
                "what": "Questions due",
                "kind": "QUESTIONS_DUE",
                "date_text": "December 5, 2026",
                "date": "2026-12-05",
            },
            deep=True,
        )
    )
    extraction.dates.append(
        extraction.dates[0].model_copy(
            update={
                "what": "Email conference RSVP",
                "kind": "OTHER",
                "date_text": "December 1, 2026",
                "date": "2026-12-01",
            },
            deep=True,
        )
    )
    original = extraction.gate_candidates[0]
    extraction.gate_candidates = [
        original.model_copy(update={"gate_id": "gate-001", "action_date": "January 10, 2027"}),
        original.model_copy(
            update={
                "gate_id": "gate-002",
                "type": "ELIGIBILITY",
                "title": "Agency waiver",
                "needs_agency_answer": True,
            }
        ),
        original.model_copy(
            update={
                "gate_id": "gate-003",
                "type": "MANDATORY_MEETING",
                "title": "Conference RSVP",
                "action": "Email RSVP by the stated deadline.",
                "action_date": "December 2, 2026",
            }
        ),
    ]
    assessment = full_assessment()
    assessment.gates = [
        assessment.gates[0].model_copy(update={"gate_id": f"gate-00{index}"})
        for index in range(1, 4)
    ]

    rows = build_radar(extraction, assessment, date(2026, 11, 25))
    dates = {row["gate_id"]: row["action_date"] for row in rows}
    assert dates == {
        "gate-001": "2027-01-15",
        "gate-002": "2026-12-05",
        "gate-003": "2026-12-01",
    }


def test_radar_hides_unverified_consequence():
    extraction = extraction_fixture()
    extraction.gate_candidates[0].consequence = "Proposal will be rejected."
    extraction.gate_candidates[0].consequence_evidence = Evidence(
        quote="Proposal will be rejected.", page=1, verified=False, match="none"
    )
    rows = build_radar(extraction, full_assessment(), date(2027, 1, 1))
    assert rows[0]["consequence"] == "Not stated"
    assert rows[0]["consequence_evidence"] is None
