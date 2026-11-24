from conftest import extraction_fixture

from rfp_agent.schemas import Evidence, RecallResult
from rfp_agent.verify import _verify_one, merge_recall, normalize_text


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
