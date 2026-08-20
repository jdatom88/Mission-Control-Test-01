import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from mission_control.capabilities.briefing.calendar_workflow import (
    CalendarProposalWorkflow,
    ExecutionOutcome,
    ExecutionReceipt,
    ProposalStatus,
    SourceItem,
)
from mission_control.capabilities.briefing.persistence import (
    PersistenceUnavailableError,
    SqliteCalendarProposalStore,
)
from mission_control.capabilities.calendar.service import MissionControlEvent
from mission_control.runtime.calendar_storage import (
    BackupValidationError,
    PilotRuntimeStorageConfig,
    RuntimeStorageConfigurationError,
    RuntimeStorageUnavailableError,
    bootstrap_pilot_storage,
    create_consistent_backup,
    open_pilot_store,
    restore_consistent_backup,
)


def _config(tmp_path: Path) -> PilotRuntimeStorageConfig:
    state_root = tmp_path / "state-volume"
    backup_root = tmp_path / "backup-volume"
    state_root.mkdir()
    backup_root.mkdir()
    return PilotRuntimeStorageConfig(
        state_volume_root=state_root,
        state_volume_id="pilot-state-v1",
        backup_volume_root=backup_root,
        backup_volume_id="pilot-backup-v1",
    )


def _event(title: str, hour: int) -> MissionControlEvent:
    timezone = ZoneInfo("America/Los_Angeles")
    return MissionControlEvent(
        title=title,
        start=datetime(2026, 8, 28, hour, 0, tzinfo=timezone),
        end=datetime(2026, 8, 28, hour + 1, 0, tzinfo=timezone),
        description="Pilot durability validation.",
        uid=f"{title.lower().replace(' ', '-')}@mission-control.local",
    )


class _SyntheticExecutor:
    def execute(self, proposal):
        return ExecutionReceipt(
            outcome=ExecutionOutcome.DIRECT_VERIFIED,
            verified=True,
            message="Synthetic provider result; no live mutation.",
            provider="synthetic",
            event_id=proposal.operation_id,
        )


def _seed_state(store: SqliteCalendarProposalStore) -> None:
    workflow = CalendarProposalWorkflow(store)
    workflow.prepare(
        SourceItem("source-deferred", "Deferred source", "Preserve this context."),
        _event("Deferred pilot event", 9),
        proposal_id="pilot-deferred",
        rationale="Deferred recommendation remains valuable.",
    )
    workflow.defer("pilot-deferred")
    workflow.prepare(
        SourceItem("source-executed", "Executed source", "Preserve this receipt."),
        _event("Executed pilot event", 11),
        proposal_id="pilot-executed",
        rationale="Verified result must remain auditable.",
    )
    workflow.approve("pilot-executed", _SyntheticExecutor())


def test_store_can_refuse_implicit_initialization(tmp_path):
    database = tmp_path / "missing" / "calendar.sqlite3"

    with pytest.raises(PersistenceUnavailableError, match="no empty store"):
        SqliteCalendarProposalStore(database, initialize_if_missing=False)

    assert not database.exists()
    assert not database.parent.exists()


def test_environment_configuration_requires_every_value(tmp_path):
    with pytest.raises(RuntimeStorageConfigurationError, match="incomplete"):
        PilotRuntimeStorageConfig.from_environment(
            {"MISSION_CONTROL_STATE_VOLUME_ROOT": str(tmp_path)}
        )


def test_nested_state_and_backup_roots_are_rejected(tmp_path):
    with pytest.raises(RuntimeStorageConfigurationError, match="inside"):
        PilotRuntimeStorageConfig(
            state_volume_root=tmp_path,
            state_volume_id="state",
            backup_volume_root=tmp_path / "backup",
            backup_volume_id="backup",
        )


def test_bootstrap_is_explicit_and_cannot_be_repeated(tmp_path):
    config = _config(tmp_path)
    store = bootstrap_pilot_storage(config)

    assert config.database_path.is_file()
    assert store.validate_integrity().proposals == ()
    assert json.loads(config.state_marker_path.read_text())["role"] == "calendar-state"
    assert json.loads(config.backup_marker_path.read_text())["role"] == "calendar-backup"

    with pytest.raises(RuntimeStorageConfigurationError, match="already initialized"):
        bootstrap_pilot_storage(config)


def test_open_requires_marked_volumes_and_does_not_create_database(tmp_path):
    config = _config(tmp_path)

    with pytest.raises(RuntimeStorageUnavailableError, match="marker"):
        open_pilot_store(config)

    assert not config.database_path.exists()


def test_missing_expected_database_fails_without_empty_replacement(tmp_path):
    config = _config(tmp_path)
    bootstrap_pilot_storage(config)
    config.database_path.unlink()

    with pytest.raises(RuntimeStorageUnavailableError, match="no empty database"):
        open_pilot_store(config)

    assert not config.database_path.exists()


def test_wrong_volume_identity_fails_loudly(tmp_path):
    config = _config(tmp_path)
    bootstrap_pilot_storage(config)
    marker = json.loads(config.state_marker_path.read_text())
    marker["volume_id"] = "unexpected-volume"
    config.state_marker_path.write_text(json.dumps(marker))

    with pytest.raises(RuntimeStorageUnavailableError, match="does not match"):
        open_pilot_store(config)


def test_read_only_database_is_rejected_before_use(tmp_path):
    config = _config(tmp_path)
    bootstrap_pilot_storage(config)
    config.database_path.chmod(0o400)

    with pytest.raises(RuntimeStorageUnavailableError, match="read-only"):
        open_pilot_store(config)


def test_consistent_backup_is_validated_and_has_receipt(tmp_path):
    config = _config(tmp_path)
    store = bootstrap_pilot_storage(config)
    _seed_state(store)

    receipt = create_consistent_backup(
        config,
        backup_name="pilot-acceptance.sqlite3",
    )
    backup_store = SqliteCalendarProposalStore(
        receipt.backup_path,
        initialize_if_missing=False,
    )

    assert receipt.backup_path.parent == config.backup_directory
    assert receipt.proposal_count == 2
    assert receipt.audit_record_count == 5
    assert receipt.receipt_count == 1
    assert len(receipt.sha256) == 64
    assert backup_store.validate_integrity() == store.validate_integrity()


def test_backup_never_overwrites_existing_destination(tmp_path):
    config = _config(tmp_path)
    bootstrap_pilot_storage(config)
    create_consistent_backup(config, backup_name="same-name.sqlite3")

    with pytest.raises(RuntimeStorageConfigurationError, match="not be overwritten"):
        create_consistent_backup(config, backup_name="same-name.sqlite3")


def test_restore_refuses_to_overwrite_live_database(tmp_path):
    config = _config(tmp_path)
    bootstrap_pilot_storage(config)
    backup = create_consistent_backup(config, backup_name="restore.sqlite3")

    with pytest.raises(RuntimeStorageConfigurationError, match="already exists"):
        restore_consistent_backup(config, backup.backup_path)


def test_clean_restore_preserves_complete_workflow_semantics(tmp_path):
    config = _config(tmp_path)
    store = bootstrap_pilot_storage(config)
    _seed_state(store)
    expected = store.validate_integrity()
    backup = create_consistent_backup(config, backup_name="restore.sqlite3")
    config.database_path.unlink()

    receipt = restore_consistent_backup(config, backup.backup_path)
    restored = open_pilot_store(config)
    snapshot = restored.validate_integrity()
    workflow = CalendarProposalWorkflow(restored)

    assert snapshot == expected
    assert receipt.proposal_count == 2
    assert receipt.audit_record_count == 5
    assert receipt.receipt_count == 1
    assert workflow.get("pilot-deferred").status is ProposalStatus.DEFERRED
    assert workflow.get("pilot-deferred").source.context == "Preserve this context."
    assert workflow.get("pilot-executed").status is ProposalStatus.EXECUTED
    assert workflow.execution_receipt("pilot-executed").verified is True


def test_restore_rejects_backup_outside_configured_backup_directory(tmp_path):
    config = _config(tmp_path)
    bootstrap_pilot_storage(config)
    outside = tmp_path / "outside.sqlite3"
    SqliteCalendarProposalStore(outside)
    config.database_path.unlink()

    with pytest.raises(RuntimeStorageConfigurationError, match="inside"):
        restore_consistent_backup(config, outside)


def test_corrupt_backup_fails_and_does_not_publish_live_database(tmp_path):
    config = _config(tmp_path)
    bootstrap_pilot_storage(config)
    config.database_path.unlink()
    corrupt = config.backup_directory / "corrupt.sqlite3"
    corrupt.write_bytes(b"not a database")

    with pytest.raises(BackupValidationError, match="integrity validation"):
        restore_consistent_backup(config, corrupt)

    assert not config.database_path.exists()
