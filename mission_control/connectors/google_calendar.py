"""Thin Google Calendar API adapter for the Mission Control Calendar Service."""

from __future__ import annotations

import re
from datetime import datetime
from hashlib import sha256
from typing import Any, Mapping

from mission_control.capabilities.calendar.direct import (
    ConnectorOperationError,
    ProviderCalendarEvent,
)
from mission_control.capabilities.calendar.service import MissionControlEvent
from mission_control.core.connector_state import ConnectorState


GOOGLE_CALENDAR_WRITE_SCOPE = "https://www.googleapis.com/auth/calendar"


def build_google_calendar_connector(credentials: Any) -> "GoogleCalendarConnector":
    """Build the thin adapter from externally managed Google credentials."""
    from googleapiclient.discovery import build

    service = build(
        "calendar",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )
    return GoogleCalendarConnector(service)


class GoogleCalendarConnector:
    """Adapt an authorized Google Calendar API v3 service client."""

    provider_name = "google_calendar"

    def __init__(self, service: Any) -> None:
        self._service = service

    def check_write_access(self, calendar_id: str) -> ConnectorState:
        try:
            resource = (
                self._service.calendarList()
                .get(calendarId=calendar_id)
                .execute()
            )
        except Exception as exc:
            raise _classified_error(exc, operation="access") from exc

        if resource.get("accessRole") not in {"writer", "owner"}:
            return ConnectorState.INSUFFICIENT_SCOPE
        return ConnectorState.HEALTHY_DATA_FOUND

    def create_event(
        self,
        calendar_id: str,
        event_data: MissionControlEvent,
        operation_id: str,
    ) -> ProviderCalendarEvent:
        provider_event_id = _google_event_id(operation_id)
        body = _event_body(event_data, provider_event_id)
        try:
            resource = (
                self._service.events()
                .insert(
                    calendarId=calendar_id,
                    body=body,
                    sendUpdates="none",
                )
                .execute()
            )
        except Exception as exc:
            # Google returns 409 when this caller-provided event ID already exists.
            # Read it back instead of repeating the mutation.
            if _http_status(exc) == 409:
                return self.get_event(calendar_id, provider_event_id)
            raise _classified_error(exc, operation="create") from exc

        return _provider_event(resource)

    def get_event(self, calendar_id: str, event_id: str) -> ProviderCalendarEvent:
        try:
            resource = (
                self._service.events()
                .get(calendarId=calendar_id, eventId=event_id)
                .execute()
            )
        except Exception as exc:
            raise _classified_error(exc, operation="read") from exc
        return _provider_event(resource)


def _event_body(event_data: MissionControlEvent, operation_id: str) -> dict[str, Any]:
    timezone_name = getattr(event_data.start.tzinfo, "key", None)
    start: dict[str, str] = {"dateTime": event_data.start.isoformat()}
    end: dict[str, str] = {"dateTime": event_data.end.isoformat()}
    if timezone_name:
        start["timeZone"] = timezone_name
        end["timeZone"] = timezone_name

    body: dict[str, Any] = {
        "id": operation_id,
        "summary": event_data.title,
        "start": start,
        "end": end,
    }
    if event_data.description:
        body["description"] = event_data.description
    if event_data.location:
        body["location"] = event_data.location
    return body


def _google_event_id(operation_id: str) -> str:
    """Return a deterministic Google-safe ID for duplicate-safe retries."""
    if re.fullmatch(r"[a-v0-9]{5,1024}", operation_id):
        return operation_id
    return "mc" + sha256(operation_id.encode("utf-8")).hexdigest()[:30]


def _provider_event(resource: Mapping[str, Any]) -> ProviderCalendarEvent:
    try:
        event_id = str(resource["id"])
        title = str(resource.get("summary", ""))
        start_resource = resource["start"]
        end_resource = resource["end"]
        start = _parse_datetime(start_resource["dateTime"])
        end = _parse_datetime(end_resource["dateTime"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ConnectorOperationError(
            ConnectorState.EXECUTION_FAILURE,
            "Google Calendar returned an incomplete timed-event resource.",
        ) from exc

    return ProviderCalendarEvent(
        event_id=event_id,
        title=title,
        start=start,
        end=end,
        timezone_name=start_resource.get("timeZone"),
        description=str(resource.get("description", "")),
        location=str(resource.get("location", "")),
        status=str(resource.get("status", "confirmed")),
        event_url=resource.get("htmlLink"),
    )


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Google Calendar returned a timezone-naive datetime")
    return parsed


def _classified_error(exc: Exception, *, operation: str) -> ConnectorOperationError:
    status = _http_status(exc)
    if status == 401:
        state = ConnectorState.AUTH_EXPIRED
        message = "Google Calendar authorization has expired."
    elif status == 403:
        state = ConnectorState.INSUFFICIENT_SCOPE
        message = "Google Calendar is connected without required write access."
    elif status == 404 and operation == "access":
        state = ConnectorState.WRONG_ACCOUNT
        message = "The connected Google account cannot access the selected calendar."
    elif status == 404 and operation == "read":
        state = ConnectorState.HEALTHY_NO_MATCHING_DATA
        message = "Google Calendar did not return the created event during verification."
    elif status == 429 or (status is not None and status >= 500):
        state = ConnectorState.CONNECTOR_UNAVAILABLE
        message = "Google Calendar is temporarily unavailable."
    else:
        state = ConnectorState.EXECUTION_FAILURE
        message = f"Google Calendar {operation} failed."
    return ConnectorOperationError(state, message)


def _http_status(exc: Exception) -> int | None:
    response = getattr(exc, "resp", None)
    status = getattr(response, "status", None)
    return status if isinstance(status, int) else None
