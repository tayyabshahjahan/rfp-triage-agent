from datetime import date

from rfp_agent.dates import add_as_of, check_date
from rfp_agent.schemas import DateItem, Evidence


def make_date(date_text: str, iso: str) -> DateItem:
    return DateItem(
        what="Proposal due",
        kind="PROPOSAL_DUE",
        date_text=date_text,
        date=iso,
        evidence=Evidence(quote=date_text, page=1),
    )


def test_date_text_matches_iso():
    item = make_date("January 15, 2027", "2027-01-15")
    assert check_date(item) is None
    assert item.date_check == "ok"


def test_date_mismatch_creates_warning():
    item = make_date("January 8, 2027", "2027-01-15")
    assert "mismatch" in check_date(item).lower()
    assert item.date_check == "mismatch"


def test_days_remaining_and_status():
    item = make_date("January 15, 2027", "2027-01-15")
    add_as_of(item, date(2027, 1, 10))
    assert item.days_remaining == 5
    assert item.timing == "UPCOMING"
