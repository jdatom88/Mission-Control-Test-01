"""Governed, provider-neutral calendar retrieval for Mission Control briefings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Protocol

from mission_control.capabilities.calendar.direct import ConnectorOperationError
from mission_control.core.connector_state import ConnectorState, user_message


MAX_CALENDAR_READ_RESULTS = 250
DEFAULT_CALENDAR_READ_ATTEMPTS = 3
RUNTIME_UNAVAILABLE_MESSAGE = (
    "Calendar connector is healthy when tested separately; Calendar retrieval "
    "capability is unavailable in this execution runtime for this run."
)


@dataclass(frozen=True)
class CalendarReadEvent:
    """Canonical event returned by a read-only calendar connector."""

    event_id: str
    title: str
    start: datetime | date
    end: datetime | date
    all_day: bool
    timezone_name: str | None = None
    description: str = ""
    location: str = ""
    status: str = "confirmed"
    event_url: str | None = None


class CalendarReadConnector(Protocol):
    """Small read-only connector boundary consumed by briefing retrieval."""

    provider_name: str

    def list_events(
        self,
        calendar_id: str,
        time_min: datetime,
        time_max: datetime,
        *,
        max_results: int,
        timezone_name: str | None,
    ) -> tuple[CalendarReadEvent, ...]: ...


@dataclass(frozen=True)
class CalendarReadResult:
    """Fresh result for one explicit calendar window."""

    provider: str
    calendar_id: str
    time_min: datetime
    time_max: datetime
    state: ConnectorState
    events: tuple[CalendarReadEvent, ...]
    attempts: int
    retrieved_at: datetime
    message: str


def retrieve_calendar_window(
    connector: CalendarReadConnector | None,
    *,
    time_min: datetime,
    time_max: datetime,
    calendar_id: str = "primary",
    max_results: int = 100,
    timezone_name: str | None = None,
    max_attempts: int = DEFAULT_CALENDAR_READ_ATTEMPTS,
) -> CalendarReadResult:
    """Make a fresh bounded read; never reuse historical connector state.

    Read-only transient failures may be retried up to ``max_attempts``. Auth,
    scope, account, malformed-response, and runtime-capability failures are not
    retried. Every invocation returns a new timestamped result, so a later live
    success supersedes an earlier failure without consulting stale status text.
    """
    _validate_window(time_min, time_max, max_results, max_attempts)
    retrieved_at = datetime.now(timezone.utc)

    if connector is None:
        return CalendarReadResult(
            provider="google_calendar",
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
            state=ConnectorState.RUNTIME_CAPABILITY_UNAVAILABLE,
            events=(),
            attempts=0,
            retrieved_at=retrieved_at,
            message=RUNTIME_UNAVAILABLE_MESSAGE,
        )

    for attempt in range(1, max_attempts + 1):
        try:
            events = connector.list_events(
                calendar_id,
                time_min,
                time_max,
                max_results=max_results,
                timezone_name=timezone_name,
            )
        except ConnectorOperationError as exc:
            if exc.state in {
                ConnectorState.RATE_LIMITED,
                ConnectorState.CONNECTOR_UNAVAILABLE,
            } and attempt < max_attempts:
                continue
            return _failure_result(
                connector,
                calendar_id,
                time_min,
                time_max,
                exc.state,
                str(exc),
                attempt,
                retrieved_at,
            )
        except Exception:
            return _failure_result(
                connector,
                calendar_id,
                time_min,
                time_max,
                ConnectorState.UNKNOWN,
                "The calendar connector returned an unexpected read failure.",
                attempt,
                retrieved_at,
            )

        state = (
            ConnectorState.HEALTHY_DATA_FOUND
            if events
            else ConnectorState.HEALTHY_NO_MATCHING_DATA
        )
        return CalendarReadResult(
            provider=connector.provider_name,
            calendar_id=calendar_id,
            time_min=time_min,
            time_max=time_max,
            state=state,
            events=events,
            attempts=attempt,
            retrieved_at=retrieved_at,
            message=user_message(state),
        )

    raise AssertionError("calendar read attempt loop exited unexpectedly")


def _validate_window(
    time_min: datetime,
    time_max: datetime,
    max_results: int,
    max_attempts: int,
) -> None:
    if time_min.tzinfo is None or time_max.tzinfo is None:
        raise ValueError("Calendar read bounds must be timezone-aware.")
    if time_min >= time_max:
        raise ValueError("Calendar read time_min must be before time_max.")
    if not 1 <= max_results <= MAX_CALENDAR_READ_RESULTS:
        raise ValueError(
            f"Calendar read max_results must be between 1 and {MAX_CALENDAR_READ_RESULTS}."
        )
    if not 1 <= max_attempts <= DEFAULT_CALENDAR_READ_ATTEMPTS:
        raise ValueError(
            f"Calendar read max_attempts must be between 1 and {DEFAULT_CALENDAR_READ_ATTEMPTS}."
        )


def _failure_result(
    connector: CalendarReadConnector,
    calendar_id: str,
    time_min: datetime,
    time_max: datetime,
    state: ConnectorState,
    message: str,
    attempts: int,
    retrieved_at: datetime,
) -> CalendarReadResult:
    return CalendarReadResult(
        provider=connector.provider_name,
        calendar_id=calendar_id,
        time_min=time_min,
        time_max=time_max,
        state=state,
        events=(),
        attempts=attempts,
        retrieved_at=retrieved_at,
        message=message,
    )
