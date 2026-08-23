"""Pilot runtime durability boundary for briefing-calendar SQLite state.

The Stage 4 SQLite adapter remains a replaceable persistence implementation.
This module adds the operational rules that a deployed, single-runtime pilot
must satisfy before it may rely on that adapter.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from mission_control.capabilities.briefing.calendar_workflow import WorkflowSnapshot
from mission_control.capabilities.briefing.persistence import (
    PersistenceError,
    SqliteCalendarProposalStore,
)


MARKER_FORMAT_VERSION = 1
MARKER_FILENAME = ".mission-control-volume.json"
DATABASE_RELATIVE_PATH = Path("calendar/calendar-state.sqlite3")
BACKUP_RELATIVE_DIRECTORY = Path("calendar-state")
_SAFE_BACKUP_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.sqlite3\Z")


class RuntimeStorageError(PersistenceError):
    """The pilot runtime storage contract could not be satisfied."""


class RuntimeStorageConfigurationError(RuntimeStorageError):
    """The configured state and backup locations are unsafe or incomplete."""


class RuntimeStorageUnavailableError(RuntimeStorageError):
    """An expected marked runtime volume is absent or not writable."""


class BackupValidationError(RuntimeStorageError):
    """A backup or restoration failed validation and was not accepted."""


@dataclass(frozen=True)
class PilotRuntimeStorageConfig:
    """Explicit locations and identities for the two pilot storage roots."""

    state_volume_root: Path
    state_volume_id: str
    backup_volume_root: Path
    backup_volume_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "state_volume_root",
            Path(self.state_volume_root).expanduser().resolve(strict=False),
        )
        object.__setattr__(
            self,
            "backup_volume_root",
            Path(self.backup_volume_root).expanduser().resolve(strict=False),
        )
        if not self.state_volume_id.strip() or not self.backup_volume_id.strip():
            raise RuntimeStorageConfigurationError(
                "Both runtime volume identities must be explicit and non-empty."
            )
        _require_separate_roots(
            self.state_volume_root,
            self.backup_volume_root,
        )

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "PilotRuntimeStorageConfig":
        values = os.environ if environ is None else environ
        required = (
            "MISSION_CONTROL_STATE_VOLUME_ROOT",
            "MISSION_CONTROL_STATE_VOLUME_ID",
            "MISSION_CONTROL_BACKUP_VOLUME_ROOT",
            "MISSION_CONTROL_BACKUP_VOLUME_ID",
        )
        missing = tuple(name for name in required if not values.get(name, "").strip())
        if missing:
            raise RuntimeStorageConfigurationError(
                "Pilot runtime storage configuration is incomplete: "
                + ", ".join(missing)
            )
        return cls(
            state_volume_root=Path(values[required[0]]),
            state_volume_id=values[required[1]],
            backup_volume_root=Path(values[required[2]]),
            backup_volume_id=values[required[3]],
        )

    @property
    def database_path(self) -> Path:
        return self.state_volume_root / DATABASE_RELATIVE_PATH

    @property
    def backup_directory(self) -> Path:
        return self.backup_volume_root / BACKUP_RELATIVE_DIRECTORY

    @property
    def state_marker_path(self) -> Path:
        return self.state_volume_root / MARKER_FILENAME

    @property
    def backup_marker_path(self) -> Path:
        return self.backup_volume_root / MARKER_FILENAME


@dataclass(frozen=True)
class BackupReceipt:
    backup_path: Path
    created_at: datetime
    sha256: str
    proposal_count: int
    audit_record_count: int
    receipt_count: int


@dataclass(frozen=True)
class RestoreReceipt:
    restored_database_path: Path
    source_backup_path: Path
    restored_at: datetime
    sha256: str
    proposal_count: int
    audit_record_count: int
    receipt_count: int


def bootstrap_pilot_storage(
    config: PilotRuntimeStorageConfig,
) -> SqliteCalendarProposalStore:
    """Intentionally initialize new marked state and backup roots once."""

    _require_writable_directory(config.state_volume_root, "state volume")
    _require_writable_directory(config.backup_volume_root, "backup volume")
    if config.state_marker_path.exists() or config.backup_marker_path.exists():
        raise RuntimeStorageConfigurationError(
            "Pilot storage is already initialized or partially initialized; "
            "bootstrap will not replace its volume markers."
        )
    if config.database_path.exists() or config.database_path.is_symlink():
        raise RuntimeStorageConfigurationError(
            "Bootstrap refused because the runtime database path already exists."
        )

    _write_marker(
        config.backup_marker_path,
        role="calendar-backup",
        volume_id=config.backup_volume_id,
    )
    _write_marker(
        config.state_marker_path,
        role="calendar-state",
        volume_id=config.state_volume_id,
    )
    config.database_path.parent.mkdir(parents=True, exist_ok=False)
    config.backup_directory.mkdir(parents=True, exist_ok=False)
    store = SqliteCalendarProposalStore(config.database_path)
    store.validate_integrity()
    return store


def open_pilot_store(
    config: PilotRuntimeStorageConfig,
) -> SqliteCalendarProposalStore:
    """Open the expected deployed store without ever creating a replacement."""

    _validate_marked_roots(config)
    _require_writable_file(config.database_path, "calendar state database")
    _require_writable_directory(config.database_path.parent, "state directory")
    _require_writable_directory(config.backup_directory, "backup directory")
    _assert_sqlite_write_lock(config.database_path)
    store = SqliteCalendarProposalStore(
        config.database_path,
        initialize_if_missing=False,
    )
    store.validate_integrity()
    return store


def create_consistent_backup(
    config: PilotRuntimeStorageConfig,
    *,
    backup_name: str | None = None,
) -> BackupReceipt:
    """Create and semantically validate an online SQLite backup."""

    store = open_pilot_store(config)
    store.validate_integrity()
    created_at = datetime.now(UTC)
    name = backup_name or (
        "calendar-state-"
        + created_at.strftime("%Y%m%dT%H%M%S%fZ")
        + ".sqlite3"
    )
    _validate_backup_name(name)
    destination = config.backup_directory / name
    if destination.exists() or destination.is_symlink():
        raise RuntimeStorageConfigurationError(
            f"Backup destination already exists and will not be overwritten: {name}"
        )

    partial = config.backup_directory / f".{name}.{uuid4().hex}.partial"
    try:
        _sqlite_online_copy(config.database_path, partial)
        backup_snapshot = _validated_snapshot(partial)
        _publish_without_overwrite(partial, destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise

    return _backup_receipt(destination, created_at, backup_snapshot)


def inspect_consistent_backup(
    config: PilotRuntimeStorageConfig,
    backup_path: str | Path,
) -> BackupReceipt:
    """Validate an existing configured backup and return its semantic receipt."""

    _validate_marked_roots(config, require_database=False)
    try:
        source = Path(backup_path).expanduser().resolve(strict=True)
    except OSError as exc:
        raise RuntimeStorageUnavailableError(
            "The requested backup file is unavailable."
        ) from exc
    try:
        source.relative_to(config.backup_directory.resolve(strict=True))
    except ValueError as exc:
        raise RuntimeStorageConfigurationError(
            "Backup inspection is restricted to the configured backup directory."
        ) from exc
    _require_regular_file(source, "backup")
    snapshot = _validated_snapshot(source)
    created_at = datetime.fromtimestamp(source.stat().st_mtime, UTC)
    return _backup_receipt(source, created_at, snapshot)


def restore_consistent_backup(
    config: PilotRuntimeStorageConfig,
    backup_path: str | Path,
) -> RestoreReceipt:
    """Restore a validated backup only into a clean marked state volume."""

    _validate_marked_roots(config, require_database=False)
    if config.database_path.exists() or config.database_path.is_symlink():
        raise RuntimeStorageConfigurationError(
            "Restore refused because the live database destination already exists."
        )

    try:
        source = Path(backup_path).expanduser().resolve(strict=True)
    except OSError as exc:
        raise RuntimeStorageUnavailableError(
            "The requested backup file is unavailable."
        ) from exc
    try:
        source.relative_to(config.backup_directory.resolve(strict=True))
    except ValueError as exc:
        raise RuntimeStorageConfigurationError(
            "Restore source must be inside the configured backup directory."
        ) from exc
    _require_regular_file(source, "backup")
    backup_snapshot = _validated_snapshot(source)

    config.database_path.parent.mkdir(parents=True, exist_ok=True)
    _require_writable_directory(config.database_path.parent, "state directory")
    partial = config.database_path.parent / (
        f".{config.database_path.name}.{uuid4().hex}.restore-partial"
    )
    try:
        _sqlite_online_copy(source, partial)
        restored_snapshot = _validated_snapshot(partial)
        if restored_snapshot != backup_snapshot:
            raise BackupValidationError(
                "Restored state differs from the validated backup."
            )
        _publish_without_overwrite(partial, config.database_path)
    except Exception:
        partial.unlink(missing_ok=True)
        raise

    restored_store = open_pilot_store(config)
    final_snapshot = restored_store.validate_integrity()
    if final_snapshot != backup_snapshot:
        raise BackupValidationError(
            "Final restored state differs from the validated backup."
        )
    restored_at = datetime.now(UTC)
    return RestoreReceipt(
        restored_database_path=config.database_path,
        source_backup_path=source,
        restored_at=restored_at,
        sha256=_sha256(config.database_path),
        proposal_count=len(final_snapshot.proposals),
        audit_record_count=len(final_snapshot.audit_records),
        receipt_count=len(final_snapshot.receipts),
    )


def _validate_marked_roots(
    config: PilotRuntimeStorageConfig,
    *,
    require_database: bool = True,
) -> None:
    _require_writable_directory(config.state_volume_root, "state volume")
    _require_writable_directory(config.backup_volume_root, "backup volume")
    _read_and_validate_marker(
        config.state_marker_path,
        role="calendar-state",
        volume_id=config.state_volume_id,
    )
    _read_and_validate_marker(
        config.backup_marker_path,
        role="calendar-backup",
        volume_id=config.backup_volume_id,
    )
    if require_database and not config.database_path.exists():
        raise RuntimeStorageUnavailableError(
            "The marked state volume is present but its expected database is "
            "missing; no empty database was created."
        )
    if not config.backup_directory.exists():
        raise RuntimeStorageUnavailableError(
            "The marked backup volume is present but its expected backup "
            "directory is missing."
        )


def _require_separate_roots(state_root: Path, backup_root: Path) -> None:
    if state_root == backup_root:
        raise RuntimeStorageConfigurationError(
            "State and backup roots must be separate configured locations."
        )
    if state_root in backup_root.parents or backup_root in state_root.parents:
        raise RuntimeStorageConfigurationError(
            "Neither configured storage root may be inside the other."
        )


def _write_marker(path: Path, *, role: str, volume_id: str) -> None:
    payload = json.dumps(
        {
            "format_version": MARKER_FORMAT_VERSION,
            "role": role,
            "volume_id": volume_id,
        },
        sort_keys=True,
    )
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as marker:
            marker.write(payload)
            marker.flush()
            os.fsync(marker.fileno())
    except OSError as exc:
        raise RuntimeStorageUnavailableError(
            f"Could not initialize runtime volume marker: {path}"
        ) from exc


def _read_and_validate_marker(path: Path, *, role: str, volume_id: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise RuntimeStorageUnavailableError(
            f"Expected {role} volume marker is unavailable; runtime stopped."
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeStorageUnavailableError(
            f"The {role} volume marker is unreadable or corrupt."
        ) from exc
    expected = {
        "format_version": MARKER_FORMAT_VERSION,
        "role": role,
        "volume_id": volume_id,
    }
    if payload != expected:
        raise RuntimeStorageUnavailableError(
            f"The mounted {role} volume identity does not match configuration."
        )


def _require_writable_directory(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_dir():
        raise RuntimeStorageUnavailableError(
            f"The configured {label} is unavailable or is not a directory."
        )
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o222 == 0:
        raise RuntimeStorageUnavailableError(
            f"The configured {label} is read-only."
        )
    probe = path / f".mission-control-write-check-{uuid4().hex}"
    try:
        descriptor = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        probe.unlink()
    except OSError as exc:
        probe.unlink(missing_ok=True)
        raise RuntimeStorageUnavailableError(
            f"The configured {label} is not writable."
        ) from exc


def _require_regular_file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise RuntimeStorageUnavailableError(
            f"The configured {label} is unavailable or not a regular file."
        )


def _require_writable_file(path: Path, label: str) -> None:
    _require_regular_file(path, label)
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o222 == 0:
        raise RuntimeStorageUnavailableError(
            f"The configured {label} is read-only."
        )


def _assert_sqlite_write_lock(path: Path) -> None:
    try:
        with sqlite3.connect(path, timeout=5) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.rollback()
    except sqlite3.Error as exc:
        raise RuntimeStorageUnavailableError(
            "The calendar state database cannot obtain a write lock."
        ) from exc


def _validate_backup_name(name: str) -> None:
    if not _SAFE_BACKUP_NAME.fullmatch(name):
        raise RuntimeStorageConfigurationError(
            "Backup name must be a simple .sqlite3 filename containing only "
            "letters, numbers, dots, underscores, and hyphens."
        )


def _sqlite_online_copy(source: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise RuntimeStorageConfigurationError(
            "Temporary backup or restore destination unexpectedly exists."
        )
    try:
        with sqlite3.connect(source, timeout=5) as source_connection:
            with sqlite3.connect(destination, timeout=5) as target_connection:
                source_connection.backup(target_connection)
                target_connection.commit()
        destination.chmod(0o600)
    except (OSError, sqlite3.Error) as exc:
        raise BackupValidationError(
            "SQLite could not create a consistent backup copy."
        ) from exc


def _validated_snapshot(path: Path) -> WorkflowSnapshot:
    try:
        store = SqliteCalendarProposalStore(path, initialize_if_missing=False)
        return store.validate_integrity()
    except (PersistenceError, OSError, sqlite3.Error) as exc:
        raise BackupValidationError(
            "SQLite backup or restore candidate failed integrity validation."
        ) from exc


def _publish_without_overwrite(partial: Path, destination: Path) -> None:
    try:
        os.link(partial, destination)
        partial.unlink()
        _fsync_directory(destination.parent)
    except FileExistsError as exc:
        raise RuntimeStorageConfigurationError(
            f"Destination appeared during publication and was not overwritten: "
            f"{destination}"
        ) from exc
    except OSError as exc:
        raise RuntimeStorageUnavailableError(
            f"Validated state could not be published safely: {destination}"
        ) from exc


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _backup_receipt(
    path: Path,
    created_at: datetime,
    snapshot: WorkflowSnapshot,
) -> BackupReceipt:
    return BackupReceipt(
        backup_path=path,
        created_at=created_at,
        sha256=_sha256(path),
        proposal_count=len(snapshot.proposals),
        audit_record_count=len(snapshot.audit_records),
        receipt_count=len(snapshot.receipts),
    )
