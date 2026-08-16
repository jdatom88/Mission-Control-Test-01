from datetime import datetime
from zoneinfo import ZoneInfo

from mission_control.capabilities.calendar.direct import (
    ConnectorOperationError,
    ProviderCalendarEvent,
    create_event_with_readback,
)
from mission_control.capabilities.calendar.service import MissionControlEvent
from mission_control.core.connector_state import ConnectorState


def _source_event() -> MissionControlEvent:
    timezone = ZoneInfo("America/Los_Angeles")
    return MissionControlEvent(
        title="Mission Control Direct Calendar Test",
        start=datetime(2026, 8, 17, 9, 0, tzinfo=timezone),
        end=datetime(2026, 8, 17, 9, 45, tzinfo=timezone),
        description="Read-back verification",
        location="Las Vegas",
    )


class FakeConnector:
    provider_name = "fake_calendar"

    def __init__(self) -> None:
        self.access_state = ConnectorState.HEALTHY_DATA_FOUND
        self.created = False
        self.operation_id: str | None = None
        self.readback_title: str | None = None
        self.failure: ConnectorOperationError | None = None

    def check_write_access(self, calendar_id: str) -> ConnectorState:
        return self.access_state

    def create_event(self, calendar_id, event_data, operation_id):
        if self.failure:
            raise self.failure
        self.created = True
        self.operation_id = operation_id
        return _provider_event(event_data, operation_id)

    def get_event(self, calendar_id, event_id):
        source = _source_event()
        recovered = _provider_event(source, event_id)
        if self.readback_title is not None:
            return ProviderCalendarEvent(
                event_id=recovered.event_id,
                title=self.readback_title,
                start=recovered.start,
                end=recovered.end,
                timezone_name=recovered.timezone_name,
                description=recovered.description,
                location=recovered.location,
                status=recovered.status,
                event_url=recovered.event_url,
            )
        return recovered


def _provider_event(source: MissionControlEvent, event_id: str) -> ProviderCalendarEvent:
    return ProviderCalendarEvent(
        event_id=event_id,
        title=source.title,
        start=source.start,
        end=source.end,
        timezone_name="America/Los_Angeles",
        description=source.description,
        location=source.location,
        event_url="https://calendar.example/event",
    )


def test_direct_create_requires_provider_readback():
    connector = FakeConnector()

    result = create_event_with_readback(
        _source_event(),
        connector,
        operation_id="mcstage2readback01",
    )

    assert result.verified is True
    assert result.state is ConnectorState.HEALTHY_DATA_FOUND
    assert result.event_id == "mcstage2readback01"
    assert connector.operation_id == result.operation_id


def test_readback_mismatch_fails_loudly():
    connector = FakeConnector()
    connector.readback_title = "Changed by provider"

    result = create_event_with_readback(_source_event(), connector)

    assert result.verified is False
    assert result.state is ConnectorState.VERIFICATION_FAILURE
    assert "title changed" in result.message
    assert result.event_id is not None


def test_access_failure_prevents_creation():
    connector = FakeConnector()
    connector.access_state = ConnectorState.WRONG_ACCOUNT

    result = create_event_with_readback(_source_event(), connector)

    assert result.verified is False
    assert result.state is ConnectorState.WRONG_ACCOUNT
    assert connector.created is False


def test_connector_failure_preserves_classified_state_and_operation_id():
    connector = FakeConnector()
    connector.failure = ConnectorOperationError(
        ConnectorState.AUTH_EXPIRED,
        "Authorization expired.",
    )

    result = create_event_with_readback(
        _source_event(),
        connector,
        operation_id="mcretryableoperation01",
    )

    assert result.verified is False
    assert result.state is ConnectorState.AUTH_EXPIRED
    assert result.operation_id == "mcretryableoperation01"
