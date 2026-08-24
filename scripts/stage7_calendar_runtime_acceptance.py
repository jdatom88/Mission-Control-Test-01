"""Synthetic end-to-end acceptance for the Calendar Runtime Assembly."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from mission_control.capabilities.briefing.calendar_runtime import (
    CalendarRuntimeAssembly,
)
from mission_control.capabilities.briefing.calendar_workflow import (
    CalendarProposalWorkflow,
    ExecutionOutcome,
    ExecutionReceipt,
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


class SyntheticCalendarConnector:
    provider_name = "synthetic_calendar"

    def list_events(self, *args, **kwargs):
        return (
            CalendarReadEvent(
                event_id="existing-event-001",
                title="Existing operating review",
                start=datetime(2026, 8, 26, 9, 0, tzinfo=TIMEZONE),
                end=datetime(2026, 8, 26, 10, 0, tzinfo=TIMEZONE),
                all_day=False,
                timezone_name="America/Los_Angeles",
            ),
        )


class SyntheticVerifiedExecutor:
    def execute(self, proposal):
        return ExecutionReceipt(
            outcome=ExecutionOutcome.DIRECT_VERIFIED,
            verified=True,
            message="Synthetic event created and independently read back.",
            provider="synthetic_calendar",
            event_id=f"verified-{proposal.operation_id}",
        )

    def recover(self, proposal):
        return self.execute(proposal)


def _runtime(database: Path) -> CalendarRuntimeAssembly:
    return CalendarRuntimeAssembly(
        CalendarProposalWorkflow(SqliteCalendarProposalStore(database)),
        SyntheticCalendarConnector(),
    )


def _assemble(runtime: CalendarRuntimeAssembly):
    return runtime.assemble(
        time_min=datetime(2026, 8, 24, 0, 0, tzinfo=TIMEZONE),
        time_max=datetime(2026, 8, 31, 0, 0, tzinfo=TIMEZONE),
        timezone_name="America/Los_Angeles",
        final_queue=True,
    )


def main() -> None:
    with TemporaryDirectory(prefix="mission-control-stage7-") as directory:
        database = Path(directory) / "calendar-state.db"

        first = _runtime(database)
        proposal = first.prepare(
            SourceItem(
                source_id="synthetic-email-001",
                heading="Client implementation deadline",
                context="The client requested a readiness review before launch.",
            ),
            MissionControlEvent(
                title="Client launch readiness review",
                start=datetime(2026, 8, 27, 14, 0, tzinfo=TIMEZONE),
                end=datetime(2026, 8, 27, 15, 0, tzinfo=TIMEZONE),
                description="Confirm final launch readiness.",
            ),
            proposal_id="calendar-runtime-acceptance-001",
            rationale="The review reduces launch risk.",
            assumptions=("Client availability is not yet confirmed.",),
            conflicts=("No known conflicts.",),
        )
        assembled = _assemble(first)
        assert assembled.calendar_read.state is ConnectorState.HEALTHY_DATA_FOUND
        assert "Existing operating review" in assembled.calendar_context
        assert "synthetic-email-001" in assembled.inline_proposals[0]
        assert "Approve | Edit | Reject | Defer" in assembled.approval_queue
        first.defer(proposal.proposal_id)

        second = _runtime(database)
        assert second.workflow.get(proposal.proposal_id).status is ProposalStatus.DEFERRED
        second.edit(
            proposal.proposal_id,
            MissionControlEvent(
                title="Client launch readiness review",
                start=datetime(2026, 8, 27, 15, 0, tzinfo=TIMEZONE),
                end=datetime(2026, 8, 27, 16, 0, tzinfo=TIMEZONE),
                description="Confirm final launch readiness.",
            ),
        )
        result = second.approve(proposal.proposal_id, SyntheticVerifiedExecutor())
        assert result.proposal.status is ProposalStatus.EXECUTED
        assert result.receipt and result.receipt.verified

        third = _runtime(database)
        assert third.workflow.active_queue() == ()
        assert len(third.workflow.audit_history) == 5
        receipt = third.workflow.execution_receipt(proposal.proposal_id)
        assert receipt and receipt.verified
        assert receipt.event_id == f"verified-{result.proposal.operation_id}"

    print("STAGE7_CALENDAR_RUNTIME_ACCEPTANCE=PASS")
    print("FRESH_READ_AND_REINFORCED_QUEUE=VERIFIED")
    print("DURABLE_DECISION_AND_RESTART=VERIFIED")
    print("SYNTHETIC_PROVIDER_VERIFICATION=VERIFIED")
    print("LIVE_CALENDAR_MUTATIONS=0")


if __name__ == "__main__":
    main()
