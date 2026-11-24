from datetime import UTC, datetime

from icalendar import Calendar

from rfp_agent.ics import build_ics


def test_ics_parses_and_converts_timed_event_to_utc():
    data = build_ics(
        [
            {
                "title": "Proposal due",
                "date": "2027-01-15",
                "time": "3:00 PM",
                "timezone": "America/Los_Angeles",
                "source": "deadline",
                "evidence": {
                    "quote": (
                        "Proposals must arrive in the procurement portal no later than "
                        "3:00 PM Pacific Time on the stated due date."
                    ),
                    "page": 4,
                },
            },
            {
                "title": "Register for portal",
                "date": "2027-01-14",
                "time": None,
                "timezone": None,
                "source": "gate",
                "evidence": {"quote": "Register before submission", "page": 8},
            },
        ],
        now=datetime(2026, 11, 25, tzinfo=UTC),
    )
    assert b"\r\n" in data
    assert all(len(line) <= 75 for line in data.split(b"\r\n") if line)
    assert any(line.startswith(b" ") for line in data.split(b"\r\n"))
    calendar = Calendar.from_ical(data)
    events = [component for component in calendar.walk() if component.name == "VEVENT"]
    assert len(events) == 2
    assert events[0].decoded("DTSTART").hour == 23
    assert events[1].decoded("DTSTART").isoformat() == "2027-01-14"


def test_ics_invalid_time_falls_back_to_all_day():
    data = build_ics(
        [
            {
                "title": "Date with unclear time",
                "date": "2027-02-01",
                "time": "time to be confirmed",
                "timezone": "America/New_York",
                "source": "deadline",
                "evidence": {"quote": "February 1, time to be confirmed", "page": 2},
            }
        ],
        now=datetime(2026, 11, 25, tzinfo=UTC),
    )
    calendar = Calendar.from_ical(data)
    event = next(component for component in calendar.walk() if component.name == "VEVENT")
    assert event.decoded("DTSTART").isoformat() == "2027-02-01"


def test_ics_accepts_explicit_month_name_date():
    data = build_ics(
        [
            {
                "title": "Mandatory meeting action",
                "date": "December 3, 2026, 9:00 AM",
                "time": None,
                "timezone": None,
                "source": "gate",
                "evidence": {"quote": "December 3, 2026 at 9:00 AM", "page": 3},
            }
        ],
        now=datetime(2026, 11, 25, tzinfo=UTC),
    )
    calendar = Calendar.from_ical(data)
    event = next(component for component in calendar.walk() if component.name == "VEVENT")
    assert event.decoded("DTSTART").isoformat() == "2026-12-03"


def test_ics_skips_unparseable_date():
    data = build_ics(
        [
            {
                "title": "Unknown date",
                "date": "Not stated",
                "time": None,
                "timezone": None,
                "source": "gate",
                "evidence": {"quote": "Timing will be announced", "page": 3},
            }
        ],
        now=datetime(2026, 11, 25, tzinfo=UTC),
    )
    calendar = Calendar.from_ical(data)
    assert not [component for component in calendar.walk() if component.name == "VEVENT"]
