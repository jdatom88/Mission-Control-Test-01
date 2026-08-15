"""Mission Control Calendar Service.

All Mission Control subsystems should route calendar-file generation through
this module rather than constructing raw ICS text.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from icalendar import Calendar, Event


@dataclass(frozen=True)
class MissionControlEvent:
    title: str
    start: datetime
    end: datetime
    description: str = ""
    location: str = ""
    uid: str | None = None

    def validate(self) -> None:
        if not self.title.strip():
            raise ValueError("Event title is required")
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("Timed events must use timezone-aware datetimes")
        if self.end <= self.start:
            raise ValueError("Event end must occur after event start")


def export_ics(event_data: MissionControlEvent, output_path: str | Path) -> Path:
    """Generate, parse-back validate, and persist a real ICS artifact."""
    event_data.validate()

    calendar = Calendar()
    calendar.add("prodid", "-//Mission Control OS//Calendar Service//EN")
    calendar.add("version", "2.0")

    event = Event()
    event.add("uid", event_data.uid or f"{uuid4()}@mission-control.local")
    event.add("dtstamp", datetime.now(timezone.utc))
    event.add("summary", event_data.title)
    event.add("dtstart", event_data.start)
    event.add("dtend", event_data.end)
    if event_data.description:
        event.add("description", event_data.description)
    if event_data.location:
        event.add("location", event_data.location)
    calendar.add_component(event)

    payload = calendar.to_ical()

    # Parse-back gate: never advertise an artifact that cannot be read back.
    parsed = Calendar.from_ical(payload)
    recovered = [component for component in parsed.walk() if component.name == "VEVENT"]
    if len(recovered) != 1:
        raise ValueError("ICS validation failed: expected exactly one VEVENT")
    if str(recovered[0].get("summary")) != event_data.title:
        raise ValueError("ICS validation failed: event title changed during serialization")

    path = Path(output_path)
    if path.suffix.lower() != ".ics":
        raise ValueError("Calendar artifact must use the .ics extension")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)

    if not path.exists() or path.stat().st_size == 0:
        raise IOError("ICS artifact validation failed after write")

    return path
