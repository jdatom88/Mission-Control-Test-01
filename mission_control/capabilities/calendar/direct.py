"""Governed direct-calendar orchestration with provider read-back verification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from mission_control.capabilities.calendar.service import MissionControlEvent
from mission_control.core.connector_state import ConnectorState, user_message


class ConnectorOperationError(RuntimeError):
    """A provider failure already classified into Mission Control state."""

    def __init__(self, state: ConnectorState, message: str) -> None:
        super().__init__(message)
        self.state = state


@dataclass(frozen=True)
class ProviderCalendarEvent:
    """Provider-neutral event returned by a thin calendar connector."""

    event_id: str
    title: str
    start: datetime
    end: datetime
    timezone_name: str | None = None
    description: str = ""
    location: str = ""
    status: str = "confirmed"
    event_url: str | None = None


class DirectCalendarConnector(Protocol):
    """Minimal connector contract consumed by the Calendar Service."""

    provider_name: str

    def check_write_access(self, calendar_id: str) -> ConnectorState: ...

    def create_event(
        self,
        calendar_id: str,
        event_data: MissionControlEvent,
        operation_id: str,
    ) -> ProviderCalendarEvent: ...

    def get_event(self, calendar_id: str, event_id: str) -> ProviderCalendarEvent: ...


@dataclass(frozen=True)
class DirectCalendarResult:
    """Truthful result of a direct create-and-read-back attempt."""

    provider: str
    calendar_id: str
    operation_id: str
    state: ConnectorState
    verified: bool
    message: str
    event_id: str | None = None
    event_url: str | None = None


def create_event_with_readback(
    event_data: MissionControlEvent,
    connector: DirectCalendarConnector,
    *,
    calendar_id: str = "primary",
    operation_id: str | None = None,
) -> DirectCalendarResult:
    """Create an authorized event and verify it with a separate provider read."""
    event_data.validate()
    resolved_operation_id = operation_id or f"mc{uuid4().hex}"

    try:
        access_state = connector.check_write_access(calendar_id)
        if access_state is not ConnectorState.HEALTHY_DATA_FOUND:
            return _failure(
                connector,
                calendar_id,
                resolved_operation_id,
                access_state,
                user_message(access_state),
            )

        created = connector.create_event(
            calendar_id,
            event_data,
            resolved_operation_id,
        )
        recovered = connector.get_event(calendar_id, created.event_id)
    except ConnectorOperationError as exc:
        return _failure(
            connector,
            calendar_id,
            resolved_operation_id,
            exc.state,
            str(exc),
        )
    except Exception:
        return _failure(
            connector,
            calendar_id,
            resolved_operation_id,
            ConnectorState.UNKNOWN,
            "The calendar connector returned an unexpected failure.",
        )

    mismatches = _semantic_mismatches(event_data, created.event_id, recovered)
    if mismatches:
        return DirectCalendarResult(
            provider=connector.provider_name,
            calendar_id=calendar_id,
            operation_id=resolved_operation_id,
            event_id=created.event_id,
            event_url=recovered.event_url or created.event_url,
            state=ConnectorState.VERIFICATION_FAILURE,
            verified=False,
            message="Calendar event was created but read-back verification failed: "
            + "; ".join(mismatches),
        )

    return DirectCalendarResult(
        provider=connector.provider_name,
        calendar_id=calendar_id,
        operation_id=resolved_operation_id,
        event_id=recovered.event_id,
        event_url=recovered.event_url or created.event_url,
        state=ConnectorState.HEALTHY_DATA_FOUND,
        verified=True,
        message="Calendar event created and verified by provider read-back.",
    )


def _failure(
    connector: DirectCalendarConnector,
    calendar_id: str,
    operation_id: str,
    state: ConnectorState,
    message: str,
) -> DirectCalendarResult:
    return DirectCalendarResult(
        provider=connector.provider_name,
        calendar_id=calendar_id,
        operation_id=operation_id,
        state=state,
        verified=False,
        message=message,
    )


def _semantic_mismatches(
    source: MissionControlEvent,
    created_event_id: str,
    recovered: ProviderCalendarEvent,
) -> list[str]:
    mismatches: list[str] = []

    if not recovered.event_id or recovered.event_id != created_event_id:
        mismatches.append("provider event ID changed")
    if recovered.status == "cancelled":
        mismatches.append("provider returned a cancelled event")
    if recovered.title != source.title:
        mismatches.append("title changed")
    if recovered.description != source.description:
        mismatches.append("description changed")
    if recovered.location != source.location:
        mismatches.append("location changed")
    if not _same_instant(recovered.start, source.start):
        mismatches.append("start changed")
    if not _same_instant(recovered.end, source.end):
        mismatches.append("end changed")

    expected_timezone = getattr(source.start.tzinfo, "key", None)
    if expected_timezone and recovered.timezone_name != expected_timezone:
        mismatches.append("timezone changed")

    return mismatches


def _same_instant(left: datetime, right: datetime) -> bool:
    if left.tzinfo is None or right.tzinfo is None:
        return False
    return left.astimezone(timezone.utc) == right.astimezone(timezone.utc)
