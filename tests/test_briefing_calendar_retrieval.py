from datetime import datetime
from zoneinfo import ZoneInfo

from mission_control.capabilities.briefing.calendar_retrieval import (
    retrieve_calendar_for_briefing,
)
from mission_control.core.connector_state import ConnectorState


class EmptyCalendarConnector:
    provider_name = "fake_calendar"

    def list_events(self, *args, **kwargs):
        return ()


def test_briefing_boundary_performs_fresh_governed_read():
    timezone = ZoneInfo("America/Los_Angeles")

    result = retrieve_calendar_for_briefing(
        EmptyCalendarConnector(),
        time_min=datetime(2026, 8, 24, 0, 0, tzinfo=timezone),
        time_max=datetime(2026, 8, 25, 0, 0, tzinfo=timezone),
        timezone_name="America/Los_Angeles",
    )

    assert result.state is ConnectorState.HEALTHY_NO_MATCHING_DATA
    assert result.attempts == 1


def test_briefing_boundary_reports_runtime_capability_truthfully():
    timezone = ZoneInfo("America/Los_Angeles")

    result = retrieve_calendar_for_briefing(
        None,
        time_min=datetime(2026, 8, 24, 0, 0, tzinfo=timezone),
        time_max=datetime(2026, 8, 25, 0, 0, tzinfo=timezone),
    )

    assert result.state is ConnectorState.RUNTIME_CAPABILITY_UNAVAILABLE
    assert "Google Calendar unavailable" not in result.message
