"""Separate-process pilot storage backup/restore acceptance.

All state and synthetic provider behavior stay inside a temporary directory.
No live calendar connector is imported or invoked.
"""

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
from mission_control.capabilities.calendar.service import MissionControlEvent
from mission_control.runtime.calendar_storage import (
    PilotRuntimeStorageConfig,
    RuntimeStorageUnavailableError,
    bootstrap_pilot_storage,
    create_consistent_backup,
    open_pilot_store,
    restore_consistent_backup,
)


DEFERRED_ID = "stage5-deferred-proposal"
EXECUTED_ID = "stage5-executed-proposal"
BACKUP_NAME = "stage5-acceptance.sqlite3"


def _config(state_root: Path, backup_root: Path) -> PilotRuntimeStorageConfig:
    return PilotRuntimeStorageConfig(
        state_volume_root=state_root,
        state_volume_id="stage5-state-volume",
        backup_volume_root=backup_root,
        backup_volume_id="stage5-backup-volume",
    )


def _event(title: str, hour: int) -> MissionControlEvent:
    timezone = ZoneInfo("America/Los_Angeles")
    return MissionControlEvent(
        title=title,
        start=datetime(2026, 8, 28, hour, 0, tzinfo=timezone),
        end=datetime(2026, 8, 28, hour + 1, 0, tzinfo=timezone),
        description="Synthetic Stage 5 acceptance; no live calendar mutation.",
        uid=f"stage5-{hour}@mission-control.local",
    )


class _SyntheticVerifiedExecutor:
    def execute(self, proposal):
        return ExecutionReceipt(
            outcome=ExecutionOutcome.DIRECT_VERIFIED,
            verified=True,
            message="Synthetic verified result; no provider was called.",
            provider="synthetic-stage5",
            event_id=proposal.operation_id,
        )


def _bootstrap_and_seed(state_root: Path, backup_root: Path) -> None:
    store = bootstrap_pilot_storage(_config(state_root, backup_root))
    workflow = CalendarProposalWorkflow(store)
    workflow.prepare(
        SourceItem(
            "stage5-deferred-source",
            "Deferred acceptance source",
            "This value context must survive loss and restoration.",
        ),
        _event("Stage 5 deferred acceptance", 9),
        proposal_id=DEFERRED_ID,
        rationale="The approval queue must survive runtime replacement.",
    )
    workflow.defer(DEFERRED_ID)
    workflow.prepare(
        SourceItem(
            "stage5-executed-source",
            "Executed acceptance source",
            "This verified receipt must remain auditable.",
        ),
        _event("Stage 5 executed acceptance", 11),
        proposal_id=EXECUTED_ID,
        rationale="Verified history prevents duplicate execution.",
    )
    workflow.approve(EXECUTED_ID, _SyntheticVerifiedExecutor())


def _backup(state_root: Path, backup_root: Path) -> None:
    config = _config(state_root, backup_root)
    receipt = create_consistent_backup(config, backup_name=BACKUP_NAME)
    assert receipt.proposal_count == 2
    assert receipt.audit_record_count == 5
    assert receipt.receipt_count == 1
    assert len(receipt.sha256) == 64


def _simulate_loss(state_root: Path, backup_root: Path) -> None:
    config = _config(state_root, backup_root)
    snapshot = open_pilot_store(config).validate_integrity()
    assert len(snapshot.proposals) == 2
    database = config.database_path.resolve(strict=True)
    database.relative_to(state_root.resolve(strict=True))
    database.unlink()
    assert not config.database_path.exists()


def _restore(state_root: Path, backup_root: Path) -> None:
    config = _config(state_root, backup_root)
    try:
        open_pilot_store(config)
    except RuntimeStorageUnavailableError as exc:
        assert "no empty database was created" in str(exc)
    else:
        raise AssertionError("missing live database did not fail loudly")
    assert not config.database_path.exists()
    receipt = restore_consistent_backup(
        config,
        config.backup_directory / BACKUP_NAME,
    )
    assert receipt.proposal_count == 2
    assert receipt.audit_record_count == 5
    assert receipt.receipt_count == 1


def _verify(state_root: Path, backup_root: Path) -> None:
    workflow = CalendarProposalWorkflow(
        open_pilot_store(_config(state_root, backup_root))
    )
    deferred = workflow.get(DEFERRED_ID)
    executed = workflow.get(EXECUTED_ID)
    receipt = workflow.execution_receipt(EXECUTED_ID)
    assert deferred.status is ProposalStatus.DEFERRED
    assert deferred.source.context == (
        "This value context must survive loss and restoration."
    )
    assert executed.status is ProposalStatus.EXECUTED
    assert workflow.active_queue() == (deferred,)
    assert receipt and receipt.verified is True
    assert receipt.provider == "synthetic-stage5"
    assert [record.action for record in workflow.audit_history] == [
        AuditAction.PREPARE,
        AuditAction.DEFER,
        AuditAction.PREPARE,
        AuditAction.APPROVE,
        AuditAction.EXECUTE,
    ]


_PHASES = {
    "bootstrap": _bootstrap_and_seed,
    "backup": _backup,
    "loss": _simulate_loss,
    "restore": _restore,
    "verify": _verify,
}


def _run_orchestrator() -> None:
    with tempfile.TemporaryDirectory(prefix="mission-control-stage5-") as directory:
        root = Path(directory)
        state_root = root / "state-volume"
        backup_root = root / "backup-volume"
        state_root.mkdir()
        backup_root.mkdir()
        for phase in _PHASES:
            subprocess.run(
                [
                    sys.executable,
                    __file__,
                    phase,
                    str(state_root),
                    str(backup_root),
                ],
                check=True,
            )
    print("STAGE5_SEPARATE_PROCESS_DURABILITY_ACCEPTANCE=PASS")
    print("BACKUP_RESTORE_SEMANTICS=VERIFIED")
    print("MISSING_STORE_FAIL_LOUD=VERIFIED")
    print("LIVE_CALENDAR_MUTATIONS=0")


def main() -> None:
    if len(sys.argv) == 1:
        _run_orchestrator()
        return
    if len(sys.argv) != 4 or sys.argv[1] not in _PHASES:
        raise SystemExit(
            "Usage: stage5_runtime_durability_acceptance.py "
            "[bootstrap|backup|loss|restore|verify STATE_ROOT BACKUP_ROOT]"
        )
    _PHASES[sys.argv[1]](Path(sys.argv[2]), Path(sys.argv[3]))


if __name__ == "__main__":
    main()
