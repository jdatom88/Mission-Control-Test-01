from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from icalendar import Calendar

from mission_control.capabilities.calendar.service import MissionControlEvent, export_ics


def test_generates_real_parseable_ics(tmp_path):
    tz = ZoneInfo("America/Los_Angeles")
    source = MissionControlEvent(
        title="Mission Control Calendar Test",
        start=datetime(2026, 8, 15, 18, 0, tzinfo=tz),
        end=datetime(2026, 8, 15, 18, 45, tzinfo=tz),
        description="Comma, semicolon; and\nmultiline content.",
    )
    artifact = export_ics(source, tmp_path / "test.ics")

    assert artifact.exists()
    parsed = Calendar.from_ical(artifact.read_bytes())
    events = [component for component in parsed.walk() if component.name == "VEVENT"]
    assert len(events) == 1
    assert str(events[0].get("summary")) == source.title


def test_rejects_naive_datetime(tmp_path):
    source = MissionControlEvent(
        title="Invalid",
        start=datetime(2026, 8, 15, 18, 0),
        end=datetime(2026, 8, 15, 19, 0),
    )
    with pytest.raises(ValueError):
        export_ics(source, tmp_path / "invalid.ics")


def test_rejects_non_ics_artifact(tmp_path):
    tz = ZoneInfo("America/Los_Angeles")
    source = MissionControlEvent(
        title="Wrong extension",
        start=datetime(2026, 8, 15, 18, 0, tzinfo=tz),
        end=datetime(2026, 8, 15, 19, 0, tzinfo=tz),
    )
    with pytest.raises(ValueError):
        export_ics(source, tmp_path / "fake.txt")
