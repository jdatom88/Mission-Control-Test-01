import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from mission_control.capabilities.briefing.calendar_workflow import (
    AuditAction,
    CalendarProposalWorkflow,
    ExecutionOutcome,
    ExecutionReceipt,
    ProposalStatus,
    RecoveryRequiredError,
    SourceItem,
)
from mission_control.capabilities.briefing.persistence import (
    PersistenceCompatibilityError,
    PersistenceConflictError,
    PersistenceCorruptionError,
    PersistenceError,
    SqliteCalendarProposalStore,
)
from mission_control.capabilities.calendar.service import MissionControlEvent


def _event(*, hour: int = 14) -> MissionControlEvent:
    timezone = ZoneInfo("America/Los_Angeles")
    return MissionControlEvent(
        title="Persistent client review",
        start=datetime(2026, 8, 27, hour, 0, tzinfo=timezone),
        end=datetime(2026, 8, 27, hour + 1, 0, tzinfo=timezone),
        description="Confirm client launch readiness.",
        location="Video call",
        uid="persistent-review@mission-control.local",
    )


def _prepare(
    workflow: CalendarProposalWorkflow,
    proposal_id: str = "persistent-proposal-001",
) -> None:
    workflow.prepare(
        SourceItem(
            source_id="source-email-001",
            heading="Client launch deadline",
            context="The client requested a review before launch.",
        ),
        _event(),
        proposal_id=proposal_id,
        rationale="The review reduces launch risk.",
        assumptions=("Client availability is not yet confirmed.",),
        conflicts=("No known calendar conflicts.",),
    )


class CountingExecutor:
    def __init__(self, receipt: ExecutionReceipt | None = None) -> None:
        self.execute_count = 0
        self.recover_count = 0
        self.receipt = receipt or ExecutionReceipt(
            outcome=ExecutionOutcome.DIRECT_VERIFIED,
            verified=True,
            message="Created and verified.",
            provider="test_calendar",
            event_id="provider-event-001",
            event_url="https://calendar.example/provider-event-001",
        )

    def execute(self, proposal):
        self.execute_count += 1
        return self.receipt

    def recover(self, proposal):
        self.recover_count += 1
        return self.receipt


class CrashingExecutor:
    def execute(self, proposal):
        raise KeyboardInterrupt("synthetic process interruption")


class ExecuteOnlyExecutor:
    def __init__(self) -> None:
        self.execute_count = 0

    def execute(self, proposal):
        self.execute_count += 1
        raise AssertionError("blind execution must not be attempted")


def test_restart_restores_deferred_queue_with_context_and_timezone(tmp_path):
    database = tmp_path / "calendar-state.db"
    workflow = CalendarProposalWorkflow(SqliteCalendarProposalStore(database))
    _prepare(workflow)
    workflow.defer("persistent-proposal-001")

    restored = CalendarProposalWorkflow(SqliteCalendarProposalStore(database))
    proposal = restored.get("persistent-proposal-001")

    assert proposal.status is ProposalStatus.DEFERRED
    assert proposal.source.context == "The client requested a review before launch."
    assert proposal.rationale == "The review reduces launch risk."
    assert proposal.event.start.tzinfo.key == "America/Los_Angeles"
    assert proposal.event.uid == "persistent-review@mission-control.local"
    assert "Client launch deadline" in restored.render_queue(final=True)
    assert [record.action for record in restored.audit_history] == [
        AuditAction.PREPARE,
        AuditAction.DEFER,
    ]


def test_edit_and_verified_receipt_round_trip_without_semantic_loss(tmp_path):
    database = tmp_path / "calendar-state.db"
    workflow = CalendarProposalWorkflow(SqliteCalendarProposalStore(database))
    _prepare(workflow)
    workflow.edit("persistent-proposal-001", _event(hour=15))

    restored = CalendarProposalWorkflow(SqliteCalendarProposalStore(database))
    edited = restored.get("persistent-proposal-001")
    assert edited.version == 2
    assert edited.status is ProposalStatus.PENDING
    assert edited.event.start.hour == 15

    executor = CountingExecutor()
    result = restored.approve("persistent-proposal-001", executor)
    assert result.proposal.status is ProposalStatus.EXECUTED
    assert executor.execute_count == 1

    completed = CalendarProposalWorkflow(SqliteCalendarProposalStore(database))
    assert completed.active_queue() == ()
    assert completed.get("persistent-proposal-001").version == 2
    receipt = completed.execution_receipt("persistent-proposal-001")
    assert receipt and receipt.event_id == "provider-event-001"
    assert receipt.verified is True


def test_rejected_proposal_remains_terminal_after_restart(tmp_path):
    database = tmp_path / "calendar-state.db"
    workflow = CalendarProposalWorkflow(SqliteCalendarProposalStore(database))
    _prepare(workflow)
    workflow.reject("persistent-proposal-001")

    restored = CalendarProposalWorkflow(SqliteCalendarProposalStore(database))

    assert restored.get("persistent-proposal-001").status is ProposalStatus.REJECTED
    assert restored.active_queue() == ()
    with pytest.raises(ValueError, match="cannot be decided"):
        restored.defer("persistent-proposal-001")


def test_approval_is_durable_before_external_execution(tmp_path):
    database = tmp_path / "calendar-state.db"
    workflow = CalendarProposalWorkflow(SqliteCalendarProposalStore(database))
    _prepare(workflow)

    class InspectingExecutor(CountingExecutor):
        def execute(self, proposal):
            observed = CalendarProposalWorkflow(SqliteCalendarProposalStore(database))
            assert (
                observed.get(proposal.proposal_id).status
                is ProposalStatus.EXECUTION_PENDING
            )
            assert observed.active_queue() == ()
            return super().execute(proposal)

    executor = InspectingExecutor()
    workflow.approve("persistent-proposal-001", executor)

    assert executor.execute_count == 1


def test_interrupted_execution_is_quarantined_and_not_blindly_retried(tmp_path):
    database = tmp_path / "calendar-state.db"
    workflow = CalendarProposalWorkflow(SqliteCalendarProposalStore(database))
    _prepare(workflow)

    with pytest.raises(KeyboardInterrupt, match="synthetic process interruption"):
        workflow.approve("persistent-proposal-001", CrashingExecutor())

    restored = CalendarProposalWorkflow(SqliteCalendarProposalStore(database))
    interrupted = restored.interrupted_executions()
    assert len(interrupted) == 1
    assert interrupted[0].status is ProposalStatus.EXECUTION_PENDING
    assert restored.active_queue() == ()
    with pytest.raises(ValueError, match="cannot be decided"):
        restored.approve("persistent-proposal-001", CountingExecutor())

    unsafe = ExecuteOnlyExecutor()
    with pytest.raises(RecoveryRequiredError, match="No retry was attempted"):
        restored.recover_interrupted("persistent-proposal-001", unsafe)
    assert unsafe.execute_count == 0
    assert restored.interrupted_executions() == interrupted


def test_interrupted_execution_uses_recovery_not_normal_execute(tmp_path):
    database = tmp_path / "calendar-state.db"
    workflow = CalendarProposalWorkflow(SqliteCalendarProposalStore(database))
    _prepare(workflow)
    with pytest.raises(KeyboardInterrupt):
        workflow.approve("persistent-proposal-001", CrashingExecutor())

    restored = CalendarProposalWorkflow(SqliteCalendarProposalStore(database))
    executor = CountingExecutor()
    result = restored.recover_interrupted("persistent-proposal-001", executor)

    assert result.proposal.status is ProposalStatus.EXECUTED
    assert executor.execute_count == 0
    assert executor.recover_count == 1
    assert result.receipt and result.receipt.verified is True

    completed = CalendarProposalWorkflow(SqliteCalendarProposalStore(database))
    assert completed.interrupted_executions() == ()
    assert "Recovery result" in completed.audit_history[-1].detail


def test_stale_workflow_cannot_execute_after_another_decision(tmp_path):
    database = tmp_path / "calendar-state.db"
    original = CalendarProposalWorkflow(SqliteCalendarProposalStore(database))
    _prepare(original)
    first = CalendarProposalWorkflow(SqliteCalendarProposalStore(database))
    stale = CalendarProposalWorkflow(SqliteCalendarProposalStore(database))

    first.defer("persistent-proposal-001")
    executor = CountingExecutor()
    with pytest.raises(PersistenceConflictError, match="Reload persistent state"):
        stale.approve("persistent-proposal-001", executor)

    assert executor.execute_count == 0


def test_persistence_failure_before_approval_prevents_external_write(tmp_path):
    database = tmp_path / "calendar-state.db"
    durable = SqliteCalendarProposalStore(database)

    class FailingApprovalStore:
        def load(self):
            return durable.load()

        def save_transition(self, proposal, audit_record, *, expected, receipt=None):
            if proposal.status is ProposalStatus.EXECUTION_PENDING:
                raise PersistenceError("synthetic unavailable store")
            durable.save_transition(
                proposal,
                audit_record,
                expected=expected,
                receipt=receipt,
            )

    workflow = CalendarProposalWorkflow(FailingApprovalStore())
    _prepare(workflow)
    executor = CountingExecutor()

    with pytest.raises(PersistenceError, match="synthetic unavailable store"):
        workflow.approve("persistent-proposal-001", executor)

    assert executor.execute_count == 0
    restored = CalendarProposalWorkflow(SqliteCalendarProposalStore(database))
    assert restored.get("persistent-proposal-001").status is ProposalStatus.PENDING


def test_final_persistence_failure_never_reports_external_write_as_complete(tmp_path):
    database = tmp_path / "calendar-state.db"
    durable = SqliteCalendarProposalStore(database)

    class FailingReceiptStore:
        def load(self):
            return durable.load()

        def save_transition(self, proposal, audit_record, *, expected, receipt=None):
            if receipt is not None:
                raise PersistenceError("synthetic final-write failure")
            durable.save_transition(
                proposal,
                audit_record,
                expected=expected,
                receipt=receipt,
            )

    workflow = CalendarProposalWorkflow(FailingReceiptStore())
    _prepare(workflow)
    executor = CountingExecutor()

    with pytest.raises(PersistenceError, match="synthetic final-write failure"):
        workflow.approve("persistent-proposal-001", executor)

    assert executor.execute_count == 1
    restored = CalendarProposalWorkflow(SqliteCalendarProposalStore(database))
    assert (
        restored.get("persistent-proposal-001").status
        is ProposalStatus.EXECUTION_PENDING
    )
    assert len(restored.interrupted_executions()) == 1


def test_ics_receipt_artifact_path_survives_restart(tmp_path):
    database = tmp_path / "calendar-state.db"
    artifact = tmp_path / "event.ics"
    workflow = CalendarProposalWorkflow(SqliteCalendarProposalStore(database))
    _prepare(workflow)
    executor = CountingExecutor(
        ExecutionReceipt(
            outcome=ExecutionOutcome.ICS_VERIFIED,
            verified=True,
            message="ICS verified; manual import required.",
            provider="ics",
            artifact_path=artifact,
        )
    )
    workflow.approve("persistent-proposal-001", executor)

    restored = CalendarProposalWorkflow(SqliteCalendarProposalStore(database))
    receipt = restored.execution_receipt("persistent-proposal-001")

    assert restored.get("persistent-proposal-001").status is ProposalStatus.FALLBACK_READY
    assert receipt and receipt.artifact_path == artifact


def test_non_database_file_fails_loudly_as_corrupt(tmp_path):
    database = tmp_path / "calendar-state.db"
    database.write_bytes(b"not a sqlite database")

    with pytest.raises(PersistenceCorruptionError, match="unavailable or corrupt"):
        SqliteCalendarProposalStore(database)


def test_foreign_database_fails_loudly_as_incompatible(tmp_path):
    database = tmp_path / "calendar-state.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE unrelated(value TEXT)")

    with pytest.raises(PersistenceCompatibilityError, match="not a compatible"):
        SqliteCalendarProposalStore(database)


def test_unknown_schema_version_fails_loudly(tmp_path):
    database = tmp_path / "calendar-state.db"
    SqliteCalendarProposalStore(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE mc_metadata SET value = ? WHERE key = ?",
            ("999", "schema_version"),
        )

    with pytest.raises(PersistenceCompatibilityError, match="Unsupported"):
        SqliteCalendarProposalStore(database)


def test_corrupt_proposal_payload_fails_loudly(tmp_path):
    database = tmp_path / "calendar-state.db"
    workflow = CalendarProposalWorkflow(SqliteCalendarProposalStore(database))
    _prepare(workflow)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE proposals SET assumptions_json = ? WHERE proposal_id = ?",
            ('{"not": "a list"}', "persistent-proposal-001"),
        )

    with pytest.raises(PersistenceCorruptionError, match="proposal is corrupt"):
        CalendarProposalWorkflow(SqliteCalendarProposalStore(database))


def test_incomplete_terminal_state_without_receipt_fails_loudly(tmp_path):
    database = tmp_path / "calendar-state.db"
    workflow = CalendarProposalWorkflow(SqliteCalendarProposalStore(database))
    _prepare(workflow)
    workflow.approve("persistent-proposal-001", CountingExecutor())
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM execution_receipts")

    with pytest.raises(PersistenceCorruptionError, match="lacks an execution receipt"):
        CalendarProposalWorkflow(SqliteCalendarProposalStore(database))
