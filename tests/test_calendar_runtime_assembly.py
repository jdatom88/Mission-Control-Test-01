from datetime import date, datetime
from zoneinfo import ZoneInfo

from mission_control.capabilities.briefing.calendar_runtime import (
    CalendarRuntimeAssembly,
)
from mission_control.capabilities.briefing.calendar_workflow import (
    CalendarProposalWorkflow,
    DirectWithIcsFallbackExecutor,
    ExecutionOutcome,
    ExecutionReceipt,
    IcsProposalExecutor,
    ProposalStatus,
    SourceItem,
)
from mission_control.capabilities.briefing.persistence import (
    SqliteCalendarProposalStore,
)
from mission_control.capabilities.calendar.read import CalendarReadEvent
from mission_control.capabilities.calendar.service import MissionControlEvent
from mission_control.core.connector_state import ConnectorState


TIMEZONE = ZoneInfo("America/Los_Angeles")
WINDOW_START = datetime(2026, 8, 24, 0, 0, tzinfo=TIMEZONE)
WINDOW_END = datetime(2026, 8, 31, 0, 0, tzinfo=TIMEZONE)


class RecordingReadConnector:
    provider_name = "test_calendar"

    def __init__(self, events=()):
        self.events = tuple(events)
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
        return self.events


class RecordingExecutor:
    def __init__(self, receipt=None):
        self.proposals = []
        self.receipt = receipt or ExecutionReceipt(
            outcome=ExecutionOutcome.DIRECT_VERIFIED,
            verified=True,
            message="Created and independently verified.",
            provider="test_calendar",
            event_id="provider-event-001",
        )

    def execute(self, proposal):
        self.proposals.append(proposal)
        return self.receipt

    def recover(self, proposal):
        self.proposals.append(proposal)
        return self.receipt


def _event(*, hour=14):
    return MissionControlEvent(
        title="Client launch readiness review",
        start=datetime(2026, 8, 27, hour, 0, tzinfo=TIMEZONE),
        end=datetime(2026, 8, 27, hour + 1, 0, tzinfo=TIMEZONE),
        description="Confirm launch readiness.",
    )


def _prepare(runtime):
    return runtime.prepare(
        SourceItem(
            source_id="synthetic-email-001",
            heading="Client implementation deadline",
            context="The client requested a review before launch.",
        ),
        _event(),
        proposal_id="calendar-proposal-001",
        rationale="A readiness review reduces launch risk.",
        assumptions=("Client availability is not yet confirmed.",),
        conflicts=("No known conflicts.",),
    )


def _assemble(runtime, *, final_queue=False):
    return runtime.assemble(
        time_min=WINDOW_START,
        time_max=WINDOW_END,
        timezone_name="America/Los_Angeles",
        final_queue=final_queue,
    )


def test_one_invocation_combines_fresh_read_inline_context_and_queue():
    connector = RecordingReadConnector(
        (
            CalendarReadEvent(
                event_id="existing-001",
                title="Existing operating review",
                start=datetime(2026, 8, 26, 9, 0, tzinfo=TIMEZONE),
                end=datetime(2026, 8, 26, 10, 0, tzinfo=TIMEZONE),
                all_day=False,
                timezone_name="America/Los_Angeles",
            ),
            CalendarReadEvent(
                event_id="all-day-001",
                title="Quarter-end deadline",
                start=date(2026, 8, 28),
                end=date(2026, 8, 29),
                all_day=True,
            ),
        )
    )
    runtime = CalendarRuntimeAssembly(CalendarProposalWorkflow(), connector)
    _prepare(runtime)

    result = _assemble(runtime)

    assert result.calendar_read.state is ConnectorState.HEALTHY_DATA_FOUND
    assert len(connector.calls) == 1
    assert "Existing operating review" in result.calendar_context
    assert "Quarter-end deadline" in result.calendar_context
    assert "America/Los_Angeles" in result.calendar_context
    assert len(result.inline_proposals) == 1
    assert "synthetic-email-001" in result.inline_proposals[0]
    assert "readiness review reduces launch risk" in result.inline_proposals[0]
    assert "Approve | Edit | Reject | Defer" in result.approval_queue


def test_healthy_empty_window_is_rendered_without_provider_failure():
    runtime = CalendarRuntimeAssembly(
        CalendarProposalWorkflow(), RecordingReadConnector()
    )

    result = _assemble(runtime)

    assert result.calendar_read.state is ConnectorState.HEALTHY_NO_MATCHING_DATA
    assert "Google Calendar unavailable" not in result.calendar_context
    assert "No pending calendar proposals" in result.approval_queue


def test_runtime_capability_limit_is_truthful_for_current_invocation():
    runtime = CalendarRuntimeAssembly(CalendarProposalWorkflow(), None)

    result = _assemble(runtime)

    assert result.calendar_read.state is ConnectorState.RUNTIME_CAPABILITY_UNAVAILABLE
    assert "healthy when tested separately" in result.calendar_context
    assert "Google Calendar unavailable" not in result.calendar_context


def test_edit_requires_renewed_approval_and_defer_carries_to_final_queue():
    runtime = CalendarRuntimeAssembly(
        CalendarProposalWorkflow(), RecordingReadConnector()
    )
    _prepare(runtime)

    edited = runtime.edit("calendar-proposal-001", _event(hour=15))
    assert edited.proposal.version == 2
    assert edited.proposal.status is ProposalStatus.PENDING

    deferred = runtime.defer("calendar-proposal-001")
    assert deferred.proposal.status is ProposalStatus.DEFERRED
    result = _assemble(runtime, final_queue=True)
    assert "Final Calendar Approval Queue" in result.approval_queue
    assert "status: deferred" in result.approval_queue


def test_approval_routes_through_existing_verified_executor():
    runtime = CalendarRuntimeAssembly(
        CalendarProposalWorkflow(), RecordingReadConnector()
    )
    proposal = _prepare(runtime)
    executor = RecordingExecutor()

    result = runtime.approve(proposal.proposal_id, executor)

    assert result.proposal.status is ProposalStatus.EXECUTED
    assert result.receipt and result.receipt.verified
    assert executor.proposals[0].operation_id == proposal.operation_id
    assert runtime.workflow.active_queue() == ()


def test_reject_closes_proposal_without_execution():
    runtime = CalendarRuntimeAssembly(
        CalendarProposalWorkflow(), RecordingReadConnector()
    )
    proposal = _prepare(runtime)
    executor = RecordingExecutor()

    result = runtime.reject(proposal.proposal_id)

    assert result.proposal.status is ProposalStatus.REJECTED
    assert executor.proposals == []
    assert "No pending calendar proposals" in _assemble(runtime).approval_queue


def test_verified_ics_fallback_remains_truthful_through_runtime(tmp_path):
    runtime = CalendarRuntimeAssembly(
        CalendarProposalWorkflow(), RecordingReadConnector()
    )
    proposal = _prepare(runtime)
    failed_direct = RecordingExecutor(
        ExecutionReceipt(
            outcome=ExecutionOutcome.FAILED,
            verified=False,
            message="Provider unavailable.",
            provider="test_calendar",
        )
    )
    executor = DirectWithIcsFallbackExecutor(
        failed_direct,
        IcsProposalExecutor(tmp_path),
    )

    result = runtime.approve(proposal.proposal_id, executor)

    assert result.proposal.status is ProposalStatus.FALLBACK_READY
    assert result.receipt and result.receipt.outcome is ExecutionOutcome.ICS_VERIFIED
    assert result.receipt.artifact_path and result.receipt.artifact_path.exists()
    assert "manual calendar import required" in result.receipt.message


def test_restart_restores_queue_audit_and_verified_receipt(tmp_path):
    database = tmp_path / "calendar-state.db"
    runtime = CalendarRuntimeAssembly(
        CalendarProposalWorkflow(SqliteCalendarProposalStore(database)),
        RecordingReadConnector(),
    )
    proposal = _prepare(runtime)
    runtime.approve(proposal.proposal_id, RecordingExecutor())

    restored = CalendarRuntimeAssembly(
        CalendarProposalWorkflow(SqliteCalendarProposalStore(database)),
        RecordingReadConnector(),
    )

    assert restored.workflow.active_queue() == ()
    assert len(restored.workflow.audit_history) == 3
    receipt = restored.workflow.execution_receipt(proposal.proposal_id)
    assert receipt and receipt.event_id == "provider-event-001"
    assert receipt.verified is True
    assembled = _assemble(restored)
    assert "No pending calendar proposals" in assembled.approval_queue
