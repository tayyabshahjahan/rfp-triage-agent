from datetime import date

from rfp_agent.dates import add_as_of, check_date, normalize_date_time, normalize_timezone
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


def test_normalizes_pacific_time_to_24_hour_and_iana():
    item = make_date("January 15, 2027 at 3:00 PM Pacific Time", "2027-01-15")
    item.time = "3:00 PM"
    item.timezone = "Pacific Time"
    normalize_date_time(item)
    assert item.time == "15:00"
    assert item.timezone == "America/Los_Angeles"


def test_normalizes_timezone_embedded_in_time():
    item = make_date("January 15, 2027 at 9 AM ET", "2027-01-15")
    item.time = "9 AM ET"
    normalize_date_time(item)
    assert item.time == "09:00"
    assert item.timezone == "America/New_York"


def test_maps_all_us_timezone_names_to_iana():
    assert normalize_timezone("Pacific") == "America/Los_Angeles"
    assert normalize_timezone("Eastern") == "America/New_York"
    assert normalize_timezone("Central") == "America/Chicago"
    assert normalize_timezone("Mountain") == "America/Denver"
