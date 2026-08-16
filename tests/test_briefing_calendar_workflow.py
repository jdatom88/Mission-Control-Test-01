from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from mission_control.capabilities.briefing.calendar_workflow import (
    AuditAction,
    CalendarProposalWorkflow,
    DirectWithIcsFallbackExecutor,
    ExecutionOutcome,
    ExecutionReceipt,
    IcsProposalExecutor,
    ProposalStatus,
    SourceItem,
)
from mission_control.capabilities.calendar.service import MissionControlEvent


def _source() -> SourceItem:
    return SourceItem(
        source_id="synthetic-email-001",
        heading="Client implementation deadline",
        context="The client requested a readiness review before the August 28 launch.",
    )


def _event(*, hour: int = 14) -> MissionControlEvent:
    timezone = ZoneInfo("America/Los_Angeles")
    return MissionControlEvent(
        title="Client launch readiness review",
        start=datetime(2026, 8, 27, hour, 0, tzinfo=timezone),
        end=datetime(2026, 8, 27, hour + 1, 0, tzinfo=timezone),
        description="Review final launch readiness with the client.",
    )


class RecordingExecutor:
    def __init__(self, receipt: ExecutionReceipt | None = None) -> None:
        self.proposals = []
        self.receipt = receipt or ExecutionReceipt(
            outcome=ExecutionOutcome.DIRECT_VERIFIED,
            verified=True,
            message="Created and verified.",
            provider="test",
            event_id="event-001",
        )

    def execute(self, proposal):
        self.proposals.append(proposal)
        return self.receipt


def _prepared_workflow() -> CalendarProposalWorkflow:
    workflow = CalendarProposalWorkflow()
    workflow.prepare(
        _source(),
        _event(),
        proposal_id="calendar-proposal-001",
        rationale="A readiness review reduces launch risk.",
        assumptions=("The client is available at the proposed time.",),
        conflicts=("No known conflicts.",),
    )
    return workflow


def test_inline_and_queue_preserve_context_and_value():
    workflow = _prepared_workflow()

    inline = workflow.render_inline("calendar-proposal-001")
    queue = workflow.render_queue()

    for output in (inline, queue):
        assert "Client implementation deadline" in output
        assert "synthetic-email-001" in output
        assert "readiness review reduces launch risk" in output
    assert "awaiting decision" in inline
    assert "Approve | Edit | Reject | Defer" in queue


def test_approve_executes_exact_displayed_version_and_records_audit():
    workflow = _prepared_workflow()
    executor = RecordingExecutor()

    result = workflow.approve("calendar-proposal-001", executor)

    assert result.proposal.status is ProposalStatus.EXECUTED
    assert result.receipt and result.receipt.verified is True
    assert executor.proposals == [replace(result.proposal, status=ProposalStatus.PENDING)]
    assert [record.action for record in workflow.audit_history] == [
        AuditAction.PREPARE,
        AuditAction.APPROVE,
        AuditAction.EXECUTE,
    ]
    assert workflow.audit_history[1].decision.value == "approve"
    assert workflow.audit_history[-1].execution_outcome is ExecutionOutcome.DIRECT_VERIFIED
    assert workflow.audit_history[-1].verified is True


def test_edit_creates_new_pending_version_without_execution():
    workflow = _prepared_workflow()
    executor = RecordingExecutor()

    edited = workflow.edit("calendar-proposal-001", _event(hour=15))

    assert edited.proposal.version == 2
    assert edited.proposal.status is ProposalStatus.PENDING
    assert edited.proposal.event.start.hour == 15
    assert executor.proposals == []
    assert workflow.audit_history[-1].action is AuditAction.EDIT
    assert "requires renewed approval" in workflow.audit_history[-1].detail

    approved = workflow.approve("calendar-proposal-001", executor)
    assert approved.proposal.status is ProposalStatus.EXECUTED
    assert executor.proposals[0].version == 2


def test_reject_records_decision_without_execution():
    workflow = _prepared_workflow()
    executor = RecordingExecutor()

    result = workflow.reject("calendar-proposal-001")

    assert result.proposal.status is ProposalStatus.REJECTED
    assert executor.proposals == []
    assert workflow.active_queue() == ()
    assert workflow.audit_history[-1].action is AuditAction.REJECT


def test_defer_carries_proposal_into_final_queue_without_execution():
    workflow = _prepared_workflow()
    executor = RecordingExecutor()

    result = workflow.defer("calendar-proposal-001")
    final_queue = workflow.render_queue(final=True)

    assert result.proposal.status is ProposalStatus.DEFERRED
    assert executor.proposals == []
    assert "Final Calendar Approval Queue" in final_queue
    assert "Client launch readiness review" in final_queue
    assert "status: deferred" in final_queue


def test_verified_ics_fallback_is_not_reported_as_direct_creation(tmp_path):
    workflow = _prepared_workflow()
    failed_direct = RecordingExecutor(
        ExecutionReceipt(
            outcome=ExecutionOutcome.FAILED,
            verified=False,
            message="Provider unavailable.",
            provider="test",
        )
    )
    executor = DirectWithIcsFallbackExecutor(
        failed_direct,
        IcsProposalExecutor(tmp_path),
    )

    result = workflow.approve("calendar-proposal-001", executor)

    assert result.proposal.status is ProposalStatus.FALLBACK_READY
    assert result.receipt and result.receipt.outcome is ExecutionOutcome.ICS_VERIFIED
    assert result.receipt.artifact_path and result.receipt.artifact_path.exists()
    assert "manual calendar import required" in result.receipt.message
    assert "Direct calendar creation was not verified" in result.receipt.message


def test_verification_failure_fails_loudly_and_is_audited():
    workflow = _prepared_workflow()
    executor = RecordingExecutor(
        ExecutionReceipt(
            outcome=ExecutionOutcome.FAILED,
            verified=False,
            message="Provider read-back did not match.",
        )
    )

    result = workflow.approve("calendar-proposal-001", executor)

    assert result.proposal.status is ProposalStatus.EXECUTION_FAILED
    assert result.receipt and result.receipt.verified is False
    assert workflow.audit_history[-1].action is AuditAction.EXECUTE
    assert "did not match" in workflow.audit_history[-1].detail


def test_operation_id_is_stable_per_version_and_changes_after_edit():
    workflow = _prepared_workflow()
    first = workflow.get("calendar-proposal-001")

    assert first.operation_id == workflow.get("calendar-proposal-001").operation_id
    second = workflow.edit("calendar-proposal-001", _event(hour=15)).proposal

    assert first.operation_id != second.operation_id
    assert first.operation_id.startswith("mc")
    assert len(first.operation_id) == 32


def test_completed_proposal_cannot_be_decided_again():
    workflow = _prepared_workflow()
    workflow.reject("calendar-proposal-001")

    with pytest.raises(ValueError, match="cannot be decided"):
        workflow.defer("calendar-proposal-001")


def test_source_and_rationale_are_required():
    workflow = CalendarProposalWorkflow()

    with pytest.raises(ValueError, match="Source context is required"):
        workflow.prepare(
            SourceItem("source", "Heading", ""),
            _event(),
            rationale="Useful.",
        )

    with pytest.raises(ValueError, match="Proposal rationale is required"):
        workflow.prepare(_source(), _event(), rationale="")
