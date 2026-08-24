from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from mission_control.capabilities.calendar.direct import ConnectorOperationError
from mission_control.capabilities.calendar.service import MissionControlEvent
from mission_control.connectors.google_calendar import GoogleCalendarConnector
from mission_control.core.connector_state import ConnectorState


class FakeRequest:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def execute(self):
        if self.error:
            raise self.error
        return self.result


class FakeHttpError(Exception):
    def __init__(self, status):
        self.resp = type("Response", (), {"status": status})()


class FakeCalendarList:
    def __init__(self, request):
        self.request = request
        self.calendar_id = None

    def get(self, *, calendarId):
        self.calendar_id = calendarId
        return self.request


class FakeEvents:
    def __init__(self, insert_request, get_request, list_request=None):
        self.insert_request = insert_request
        self.get_request = get_request
        self.list_request = list_request or FakeRequest({"items": []})
        self.insert_kwargs = None
        self.get_kwargs = None
        self.list_kwargs = None

    def insert(self, **kwargs):
        self.insert_kwargs = kwargs
        return self.insert_request

    def get(self, **kwargs):
        self.get_kwargs = kwargs
        return self.get_request

    def list(self, **kwargs):
        self.list_kwargs = kwargs
        return self.list_request


class FakeService:
    def __init__(self, calendar_request, insert_request, get_request, list_request=None):
        self.calendar_list = FakeCalendarList(calendar_request)
        self.events_resource = FakeEvents(insert_request, get_request, list_request)

    def calendarList(self):
        return self.calendar_list

    def events(self):
        return self.events_resource


def _source_event():
    timezone = ZoneInfo("America/Los_Angeles")
    return MissionControlEvent(
        title="Google Connector Test",
        start=datetime(2026, 8, 18, 6, 30, tzinfo=timezone),
        end=datetime(2026, 8, 18, 17, 30, tzinfo=timezone),
        description="Direct connector validation",
        location="Las Vegas",
    )


def _google_resource(event_id="mcgoogle01"):
    return {
        "id": event_id,
        "summary": "Google Connector Test",
        "description": "Direct connector validation",
        "location": "Las Vegas",
        "status": "confirmed",
        "htmlLink": "https://calendar.google.com/event?eid=test",
        "start": {
            "dateTime": "2026-08-18T06:30:00-07:00",
            "timeZone": "America/Los_Angeles",
        },
        "end": {
            "dateTime": "2026-08-18T17:30:00-07:00",
            "timeZone": "America/Los_Angeles",
        },
    }


def test_google_adapter_uses_insert_and_get_contract():
    service = FakeService(
        FakeRequest({"accessRole": "owner"}),
        FakeRequest(_google_resource()),
        FakeRequest(_google_resource()),
    )
    connector = GoogleCalendarConnector(service)

    assert connector.check_write_access("primary") is ConnectorState.HEALTHY_DATA_FOUND
    created = connector.create_event("primary", _source_event(), "mcgoogle01")
    recovered = connector.get_event("primary", created.event_id)

    body = service.events_resource.insert_kwargs["body"]
    assert body["id"] == "mcgoogle01"
    assert body["start"]["timeZone"] == "America/Los_Angeles"
    assert service.events_resource.insert_kwargs["sendUpdates"] == "none"
    assert service.events_resource.get_kwargs == {
        "calendarId": "primary",
        "eventId": "mcgoogle01",
    }
    assert recovered.event_id == "mcgoogle01"


def test_google_adapter_rejects_read_only_calendar():
    service = FakeService(
        FakeRequest({"accessRole": "reader"}),
        FakeRequest(_google_resource()),
        FakeRequest(_google_resource()),
    )

    state = GoogleCalendarConnector(service).check_write_access("primary")

    assert state is ConnectorState.INSUFFICIENT_SCOPE


@pytest.mark.parametrize(
    ("status", "expected_state"),
    [
        (401, ConnectorState.AUTH_EXPIRED),
        (403, ConnectorState.INSUFFICIENT_SCOPE),
        (404, ConnectorState.WRONG_ACCOUNT),
        (429, ConnectorState.RATE_LIMITED),
        (503, ConnectorState.CONNECTOR_UNAVAILABLE),
    ],
)
def test_google_adapter_classifies_access_failures(status, expected_state):
    service = FakeService(
        FakeRequest(error=FakeHttpError(status)),
        FakeRequest(_google_resource()),
        FakeRequest(_google_resource()),
    )

    with pytest.raises(ConnectorOperationError) as captured:
        GoogleCalendarConnector(service).check_write_access("primary")

    assert captured.value.state is expected_state


def test_duplicate_insert_reads_existing_event_instead_of_repeating_write():
    service = FakeService(
        FakeRequest({"accessRole": "owner"}),
        FakeRequest(error=FakeHttpError(409)),
        FakeRequest(_google_resource("mcduplicate01")),
    )
    connector = GoogleCalendarConnector(service)

    recovered = connector.create_event(
        "primary",
        _source_event(),
        "mcduplicate01",
    )

    assert recovered.event_id == "mcduplicate01"
    assert service.events_resource.get_kwargs["eventId"] == "mcduplicate01"


def test_arbitrary_operation_id_is_converted_to_stable_google_event_id():
    service = FakeService(
        FakeRequest({"accessRole": "owner"}),
        FakeRequest(_google_resource("ignored-response-id")),
        FakeRequest(_google_resource()),
    )
    connector = GoogleCalendarConnector(service)

    connector.create_event("primary", _source_event(), "approval/123@example.com")
    first_id = service.events_resource.insert_kwargs["body"]["id"]
    connector.create_event("primary", _source_event(), "approval/123@example.com")
    second_id = service.events_resource.insert_kwargs["body"]["id"]

    assert first_id == second_id
    assert first_id.startswith("mc")
    assert len(first_id) == 32


def test_google_adapter_lists_bounded_timed_and_all_day_events():
    all_day = {
        "id": "all-day-1",
        "summary": "Company holiday",
        "start": {"date": "2026-08-24"},
        "end": {"date": "2026-08-25"},
    }
    service = FakeService(
        FakeRequest({"accessRole": "owner"}),
        FakeRequest(_google_resource()),
        FakeRequest(_google_resource()),
        FakeRequest({"items": [_google_resource(), all_day]}),
    )
    connector = GoogleCalendarConnector(service)
    timezone = ZoneInfo("America/Los_Angeles")

    events = connector.list_events(
        "primary",
        datetime(2026, 8, 24, 0, 0, tzinfo=timezone),
        datetime(2026, 8, 25, 0, 0, tzinfo=timezone),
        max_results=25,
        timezone_name="America/Los_Angeles",
    )

    assert service.events_resource.list_kwargs == {
        "calendarId": "primary",
        "timeMin": "2026-08-24T07:00:00Z",
        "timeMax": "2026-08-25T07:00:00Z",
        "singleEvents": True,
        "orderBy": "startTime",
        "showDeleted": False,
        "maxResults": 25,
        "timeZone": "America/Los_Angeles",
    }
    assert len(events) == 2
    assert events[0].all_day is False
    assert events[0].timezone_name == "America/Los_Angeles"
    assert events[1].all_day is True
    assert events[1].start.isoformat() == "2026-08-24"
    assert events[1].end.isoformat() == "2026-08-25"


@pytest.mark.parametrize(
    ("status", "expected_state"),
    [
        (401, ConnectorState.AUTH_EXPIRED),
        (403, ConnectorState.INSUFFICIENT_SCOPE),
        (404, ConnectorState.WRONG_ACCOUNT),
        (429, ConnectorState.RATE_LIMITED),
        (503, ConnectorState.CONNECTOR_UNAVAILABLE),
    ],
)
def test_google_adapter_classifies_list_failures(status, expected_state):
    service = FakeService(
        FakeRequest({"accessRole": "owner"}),
        FakeRequest(_google_resource()),
        FakeRequest(_google_resource()),
        FakeRequest(error=FakeHttpError(status)),
    )
    timezone = ZoneInfo("UTC")

    with pytest.raises(ConnectorOperationError) as captured:
        GoogleCalendarConnector(service).list_events(
            "primary",
            datetime(2026, 8, 24, tzinfo=timezone),
            datetime(2026, 8, 25, tzinfo=timezone),
            max_results=100,
            timezone_name=None,
        )

    assert captured.value.state is expected_state


def test_google_adapter_rejects_malformed_list_response():
    service = FakeService(
        FakeRequest({"accessRole": "owner"}),
        FakeRequest(_google_resource()),
        FakeRequest(_google_resource()),
        FakeRequest({"items": {"not": "a list"}}),
    )
    timezone = ZoneInfo("UTC")

    with pytest.raises(ConnectorOperationError) as captured:
        GoogleCalendarConnector(service).list_events(
            "primary",
            datetime(2026, 8, 24, tzinfo=timezone),
            datetime(2026, 8, 25, tzinfo=timezone),
            max_results=100,
            timezone_name=None,
        )

    assert captured.value.state is ConnectorState.EXECUTION_FAILURE
