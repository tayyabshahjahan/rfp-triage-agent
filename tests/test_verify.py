from rfp_agent.schemas import Evidence
from rfp_agent.verify import _verify_one, normalize_text


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
