from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from mission_control.capabilities.calendar.direct import ConnectorOperationError
from mission_control.capabilities.calendar.read import (
    CalendarReadEvent,
    RUNTIME_UNAVAILABLE_MESSAGE,
    retrieve_calendar_window,
)
from mission_control.core.connector_state import ConnectorState


TIMEZONE = ZoneInfo("America/Los_Angeles")
TIME_MIN = datetime(2026, 8, 24, 0, 0, tzinfo=TIMEZONE)
TIME_MAX = datetime(2026, 8, 25, 0, 0, tzinfo=TIMEZONE)


def _event() -> CalendarReadEvent:
    return CalendarReadEvent(
        event_id="event-1",
        title="Branch review",
        start=datetime(2026, 8, 24, 9, 0, tzinfo=TIMEZONE),
        end=datetime(2026, 8, 24, 10, 0, tzinfo=TIMEZONE),
        all_day=False,
        timezone_name="America/Los_Angeles",
    )


class SequencedReadConnector:
    provider_name = "fake_calendar"

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def list_events(
        self,
        calendar_id,
        time_min,
        time_max,
        *,
        max_results,
        timezone_name,
    ):
        self.calls.append(
            (calendar_id, time_min, time_max, max_results, timezone_name)
        )
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return tuple(outcome)


def test_healthy_read_with_data_returns_canonical_events():
    connector = SequencedReadConnector([[_event()]])

    result = retrieve_calendar_window(
        connector,
        time_min=TIME_MIN,
        time_max=TIME_MAX,
        timezone_name="America/Los_Angeles",
    )

    assert result.state is ConnectorState.HEALTHY_DATA_FOUND
    assert result.events == (_event(),)
    assert result.attempts == 1
    assert connector.calls[0][0] == "primary"


def test_healthy_read_with_no_matching_data_is_not_a_failure():
    result = retrieve_calendar_window(
        SequencedReadConnector([[]]),
        time_min=TIME_MIN,
        time_max=TIME_MAX,
    )

    assert result.state is ConnectorState.HEALTHY_NO_MATCHING_DATA
    assert result.events == ()
    assert "no matching data" in result.message.lower()


def test_runtime_capability_unavailable_does_not_claim_connector_failure():
    result = retrieve_calendar_window(
        None,
        time_min=TIME_MIN,
        time_max=TIME_MAX,
    )

    assert result.state is ConnectorState.RUNTIME_CAPABILITY_UNAVAILABLE
    assert result.attempts == 0
    assert result.message == RUNTIME_UNAVAILABLE_MESSAGE
    assert "connector is healthy when tested separately" in result.message


@pytest.mark.parametrize(
    "transient_state",
    [ConnectorState.RATE_LIMITED, ConnectorState.CONNECTOR_UNAVAILABLE],
)
def test_transient_read_failure_retries_up_to_three_times(transient_state):
    connector = SequencedReadConnector(
        [
            ConnectorOperationError(transient_state, "temporary"),
            ConnectorOperationError(transient_state, "temporary"),
            [_event()],
        ]
    )

    result = retrieve_calendar_window(
        connector,
        time_min=TIME_MIN,
        time_max=TIME_MAX,
    )

    assert result.state is ConnectorState.HEALTHY_DATA_FOUND
    assert result.attempts == 3
    assert len(connector.calls) == 3


def test_nontransient_failure_is_not_retried():
    connector = SequencedReadConnector(
        [ConnectorOperationError(ConnectorState.AUTH_EXPIRED, "expired")]
    )

    result = retrieve_calendar_window(
        connector,
        time_min=TIME_MIN,
        time_max=TIME_MAX,
    )

    assert result.state is ConnectorState.AUTH_EXPIRED
    assert result.attempts == 1
    assert len(connector.calls) == 1


def test_fresh_success_supersedes_prior_failure_without_stale_state():
    connector = SequencedReadConnector(
        [
            ConnectorOperationError(ConnectorState.AUTH_EXPIRED, "expired"),
            [_event()],
        ]
    )
    failed = retrieve_calendar_window(
        connector,
        time_min=TIME_MIN,
        time_max=TIME_MAX,
        max_attempts=1,
    )
    current = retrieve_calendar_window(
        connector,
        time_min=TIME_MIN,
        time_max=TIME_MAX,
    )

    assert failed.state is ConnectorState.AUTH_EXPIRED
    assert current.state is ConnectorState.HEALTHY_DATA_FOUND
    assert current.events == (_event(),)


@pytest.mark.parametrize(
    ("time_min", "time_max", "max_results", "max_attempts"),
    [
        (TIME_MAX, TIME_MIN, 100, 3),
        (TIME_MIN.replace(tzinfo=None), TIME_MAX, 100, 3),
        (TIME_MIN, TIME_MAX, 0, 3),
        (TIME_MIN, TIME_MAX, 251, 3),
        (TIME_MIN, TIME_MAX, 100, 4),
    ],
)
def test_invalid_read_bounds_fail_before_connector_call(
    time_min, time_max, max_results, max_attempts
):
    connector = SequencedReadConnector([[]])

    with pytest.raises(ValueError):
        retrieve_calendar_window(
            connector,
            time_min=time_min,
            time_max=time_max,
            max_results=max_results,
            max_attempts=max_attempts,
        )

    assert connector.calls == []
