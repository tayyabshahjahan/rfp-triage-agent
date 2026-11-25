from conftest import extraction_fixture

from rfp_agent.schemas import Evidence, RecallResult
from rfp_agent.verify import (
    _verify_one,
    merge_recall,
    normalize_gate_types,
    normalize_text,
    requirement_coverage_cues,
)


def test_normalize_joins_hyphenated_line_breaks():
    assert normalize_text("inter-\noperability") == "interoperability"


def test_exact_match():
    evidence = Evidence(quote="Submit by Friday.", page=1)
    _verify_one(evidence, ["Submit by Friday."])
    assert evidence.verified is True
    assert evidence.match == "exact"


def test_page_is_corrected_when_quote_is_elsewhere():
    evidence = Evidence(quote="Mandatory site visit", page=1)
    _verify_one(evidence, ["Introduction", "Mandatory site visit"])
    assert evidence.verified is True
    assert evidence.page == 2
    assert evidence.page_corrected is True


def test_fuzzy_match_above_threshold():
    evidence = Evidence(quote="The proposal must include all signed certification forms.", page=1)
    _verify_one(
        evidence,
        ["The proposal must include all signed certification form."],
    )
    assert evidence.verified is True
    assert evidence.match == "fuzzy"


def test_none_when_quote_is_not_supported():
    evidence = Evidence(quote="A ten million dollar budget", page=1)
    _verify_one(evidence, ["No budget is stated in this solicitation."])
    assert evidence.verified is False
    assert evidence.match == "none"


def test_recall_merge_deduplicates_existing_items_and_adds_missing_items():
    extraction = extraction_fixture()
    extraction.requirements[0].requirement_id = "FR-1"
    duplicate_requirement = extraction.requirements[0].model_copy(deep=True)
    missing_requirement = extraction.requirements[0].model_copy(
        update={"requirement_id": "FR-2", "text": "Support SSO and MFA."},
        deep=True,
    )
    duplicate_date = extraction.dates[0].model_copy(deep=True)
    missing_date = extraction.dates[0].model_copy(
        update={
            "what": "Email conference RSVP",
            "kind": "OTHER",
            "date_text": "December 1, 2026",
            "date": "2026-12-01",
        },
        deep=True,
    )

    added = merge_recall(
        extraction,
        RecallResult(
            requirements=[duplicate_requirement, missing_requirement],
            dates=[duplicate_date, missing_date],
        ),
    )

    assert added == (1, 1)
    assert [item.requirement_id for item in extraction.requirements] == ["FR-1", "FR-2"]
    assert [item.what for item in extraction.dates] == ["Proposal due", "Email conference RSVP"]


def test_recall_merge_deduplicates_same_event_with_more_specific_kind():
    extraction = extraction_fixture()
    extraction.dates[0].kind = "OTHER"
    duplicate = extraction.dates[0].model_copy(update={"kind": "ADDENDUM"}, deep=True)

    added = merge_recall(extraction, RecallResult(dates=[duplicate]))

    assert added == (0, 0)
    assert len(extraction.dates) == 1
    assert extraction.dates[0].kind == "ADDENDUM"


def test_coverage_cues_surface_unrepresented_obligations():
    extraction = extraction_fixture()
    pages = [
        "Submit through the procurement portal.\n"
        "- All Authority data must be hosted in the United States.\n"
        "The Contractor shall maintain 99.9% availability."
    ]

    cues = requirement_coverage_cues(pages, extraction)

    assert any("hosted in the United States" in cue for cue in cues)
    assert any("99.9% availability" in cue for cue in cues)
    assert not any("procurement portal" in cue for cue in cues)


def test_contact_rule_is_not_classified_as_onsite_presence():
    extraction = extraction_fixture()
    gate = extraction.gate_candidates[0]
    gate.type = "ONSITE_PRESENCE"
    gate.title = "Communication Restrictions"
    gate.requirement = "Communicate only in writing with the procurement contact."

    normalize_gate_types(extraction)

    assert gate.type == "COMMUNICATION_RESTRICTION"
