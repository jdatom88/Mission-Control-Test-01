"""Separate-process Stage 4 persistence acceptance without live mutations."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from mission_control.capabilities.briefing.calendar_workflow import (
    AuditAction,
    CalendarProposalWorkflow,
    ExecutionOutcome,
    ExecutionReceipt,
    ProposalStatus,
    SourceItem,
)
from mission_control.capabilities.briefing.persistence import (
    SqliteCalendarProposalStore,
)
from mission_control.capabilities.calendar.service import MissionControlEvent


PROPOSAL_ID = "stage4-runtime-acceptance"


def _event(hour: int = 14) -> MissionControlEvent:
    timezone = ZoneInfo("America/Los_Angeles")
    return MissionControlEvent(
        title="Stage 4 persistent-state acceptance",
        start=datetime(2026, 8, 28, hour, 0, tzinfo=timezone),
        end=datetime(2026, 8, 28, hour + 1, 0, tzinfo=timezone),
        description="Synthetic acceptance; no live calendar mutation.",
    )


def _workflow(database: Path) -> CalendarProposalWorkflow:
    return CalendarProposalWorkflow(SqliteCalendarProposalStore(database))


def _prepare_and_defer(database: Path, marker: Path) -> None:
    workflow = _workflow(database)
    workflow.prepare(
        SourceItem(
            source_id="synthetic-stage4-source",
            heading="Synthetic persistence acceptance",
            context="A durable proposal must survive briefing restarts.",
        ),
        _event(),
        proposal_id=PROPOSAL_ID,
        rationale="Restart recovery prevents forgotten or duplicate actions.",
    )
    workflow.defer(PROPOSAL_ID)
    assert marker.exists() is False


def _restore_and_edit(database: Path, marker: Path) -> None:
    workflow = _workflow(database)
    restored = workflow.get(PROPOSAL_ID)
    assert restored.status is ProposalStatus.DEFERRED
    assert restored.source.context == "A durable proposal must survive briefing restarts."
    workflow.edit(PROPOSAL_ID, _event(hour=15))
    assert marker.exists() is False


class _InterruptedExternalWrite:
    def __init__(self, marker: Path) -> None:
        self._marker = marker

    def execute(self, proposal):
        self._marker.write_text(proposal.operation_id, encoding="utf-8")
        raise KeyboardInterrupt("synthetic interruption after external side effect")


def _approve_and_interrupt(database: Path, marker: Path) -> None:
    workflow = _workflow(database)
    proposal = workflow.get(PROPOSAL_ID)
    assert proposal.version == 2
    assert proposal.status is ProposalStatus.PENDING
    try:
        workflow.approve(PROPOSAL_ID, _InterruptedExternalWrite(marker))
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("synthetic interruption did not occur")
    assert marker.read_text(encoding="utf-8") == proposal.operation_id


class _DuplicateSafeRecovery:
    def __init__(self, marker: Path) -> None:
        self._marker = marker
        self.recover_count = 0

    def execute(self, proposal):
        raise AssertionError("normal execution must not run during recovery")

    def recover(self, proposal):
        self.recover_count += 1
        assert self._marker.read_text(encoding="utf-8") == proposal.operation_id
        return ExecutionReceipt(
            outcome=ExecutionOutcome.DIRECT_VERIFIED,
            verified=True,
            message="Synthetic existing operation reconciled by deterministic ID.",
            provider="synthetic_provider",
            event_id=proposal.operation_id,
        )


def _restore_and_recover(database: Path, marker: Path) -> None:
    workflow = _workflow(database)
    assert workflow.active_queue() == ()
    assert len(workflow.interrupted_executions()) == 1
    executor = _DuplicateSafeRecovery(marker)
    result = workflow.recover_interrupted(PROPOSAL_ID, executor)
    assert result.proposal.status is ProposalStatus.EXECUTED
    assert executor.recover_count == 1


def _verify_final_state(database: Path, marker: Path) -> None:
    workflow = _workflow(database)
    proposal = workflow.get(PROPOSAL_ID)
    receipt = workflow.execution_receipt(PROPOSAL_ID)
    assert proposal.status is ProposalStatus.EXECUTED
    assert proposal.version == 2
    assert proposal.event.start.hour == 15
    assert workflow.active_queue() == ()
    assert workflow.interrupted_executions() == ()
    assert receipt and receipt.verified is True
    assert receipt.event_id == marker.read_text(encoding="utf-8")
    assert [record.action for record in workflow.audit_history] == [
        AuditAction.PREPARE,
        AuditAction.DEFER,
        AuditAction.EDIT,
        AuditAction.APPROVE,
        AuditAction.EXECUTE,
    ]
    assert "Recovery result" in workflow.audit_history[-1].detail


_PHASES = {
    "prepare": _prepare_and_defer,
    "edit": _restore_and_edit,
    "interrupt": _approve_and_interrupt,
    "recover": _restore_and_recover,
    "verify": _verify_final_state,
}


def _run_orchestrator() -> None:
    with tempfile.TemporaryDirectory(prefix="mission-control-stage4-") as directory:
        root = Path(directory)
        database = root / "calendar-state.db"
        marker = root / "synthetic-provider-operation.txt"
        for phase in _PHASES:
            subprocess.run(
                [sys.executable, __file__, phase, str(database), str(marker)],
                check=True,
            )
    print("STAGE4_SEPARATE_PROCESS_ACCEPTANCE=PASS")
    print("LIVE_CALENDAR_MUTATIONS=0")


def main() -> None:
    if len(sys.argv) == 1:
        _run_orchestrator()
        return
    if len(sys.argv) != 4 or sys.argv[1] not in _PHASES:
        raise SystemExit(
            "Usage: stage4_persistence_acceptance.py "
            "[prepare|edit|interrupt|recover|verify DATABASE MARKER]"
        )
    _PHASES[sys.argv[1]](Path(sys.argv[2]), Path(sys.argv[3]))


if __name__ == "__main__":
    main()
