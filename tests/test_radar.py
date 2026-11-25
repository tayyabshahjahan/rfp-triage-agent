from datetime import date

from conftest import extraction_fixture, full_assessment

from rfp_agent.radar import build_calendar, build_radar
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


def test_nip_gate_uses_its_own_december_18_date_not_proposal_due():
    extraction = extraction_fixture()
    original = extraction.gate_candidates[0]
    extraction.gate_candidates = [
        original.model_copy(
            update={
                "gate_id": "gate-001",
                "type": "SUBMISSION_RULES",
                "title": "Notice of Intent to Propose",
                "requirement": "Submit the Notice of Intent by December 18, 2026.",
                "action_date": "2027-01-15",
                "evidence": Evidence(
                    quote="Notice of Intent to Propose is due December 18, 2026.", page=1
                ),
            }
        ),
        original.model_copy(
            update={
                "gate_id": "gate-002",
                "type": "FORMAT_AND_FORMS",
                "title": "Signed forms",
                "requirement": "Submit all signed forms.",
                "action_date": "2027-01-15",
            }
        ),
    ]
    assessment = full_assessment()
    assessment.gates = [
        assessment.gates[0].model_copy(update={"gate_id": f"gate-00{index}"})
        for index in range(1, 3)
    ]

    rows = build_radar(extraction, assessment, date(2026, 11, 25))
    dates = {row["gate_id"]: row["action_date"] for row in rows}
    assert dates == {
        "gate-001": "2026-12-18",
        "gate-002": None,
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


def test_radar_and_calendar_deduplicate_notice_of_intent():
    extraction = extraction_fixture()
    original = extraction.gate_candidates[0]
    nip_evidence = Evidence(
        quote="Notice of Intent to Propose is due December 18, 2026.",
        page=1,
        verified=True,
        match="exact",
    )
    extraction.gate_candidates = [
        original.model_copy(
            update={
                "gate_id": "gate-001",
                "type": "SUBMISSION_RULES",
                "title": "Notice of Intent to Propose",
                "requirement": "Submit the Notice of Intent by December 18, 2026.",
                "action_date": "2026-12-18",
                "evidence": nip_evidence,
            },
            deep=True,
        ),
        original.model_copy(
            update={
                "gate_id": "gate-002",
                "type": "REGISTRATION_OR_CERT",
                "title": "Minimum Qualification 7 - NIP Filing",
                "requirement": "The proposer filed a NIP by December 18, 2026.",
                "action_date": "2026-12-18",
                "evidence": nip_evidence,
            },
            deep=True,
        ),
    ]
    assessment = full_assessment()
    assessment.gates = [
        assessment.gates[0].model_copy(update={"gate_id": gate_id})
        for gate_id in ("gate-001", "gate-002")
    ]
    extraction.dates[0] = extraction.dates[0].model_copy(
        update={
            "what": "Notice of Intent to Propose (required)",
            "kind": "OTHER",
            "date_text": "December 18, 2026, 5:00 PM Pacific",
            "date": "2026-12-18",
            "time": "17:00",
            "timezone": "America/Los_Angeles",
            "evidence": nip_evidence,
        },
        deep=True,
    )

    rows = build_radar(extraction, assessment, date(2026, 11, 25))
    events = build_calendar(extraction, rows, date(2026, 11, 25))

    assert len(rows) == 1
    assert rows[0]["action_date"] == "2026-12-18"
    assert len(events) == 1
    assert events[0]["time"] == "17:00"
