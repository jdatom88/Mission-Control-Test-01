"""Small briefing-facing boundary for fresh governed calendar retrieval."""

from __future__ import annotations

from datetime import datetime

from mission_control.capabilities.calendar.read import (
    CalendarReadConnector,
    CalendarReadResult,
    retrieve_calendar_window,
)


def retrieve_calendar_for_briefing(
    connector: CalendarReadConnector | None,
    *,
    time_min: datetime,
    time_max: datetime,
    calendar_id: str = "primary",
    timezone_name: str | None = None,
) -> CalendarReadResult:
    """Perform the current briefing run's bounded calendar attempt.

    The wrapper intentionally retains no historical status. Briefing rendering
    must use only the returned result for this run.
    """
    return retrieve_calendar_window(
        connector,
        calendar_id=calendar_id,
        time_min=time_min,
        time_max=time_max,
        timezone_name=timezone_name,
    )
