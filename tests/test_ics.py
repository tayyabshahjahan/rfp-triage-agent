from datetime import UTC, datetime

from icalendar import Calendar

from rfp_agent.ics import build_ics


def test_ics_parses_and_converts_timed_event_to_utc():
    data = build_ics(
        [
            {
                "title": "Proposal due",
                "date": "2027-01-15",
                "time": "15:00",
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
