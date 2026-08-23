from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from mission_control.runtime.calendar_storage import (
    BackupValidationError,
    PilotRuntimeStorageConfig,
    RuntimeStorageConfigurationError,
    bootstrap_pilot_storage,
    create_consistent_backup,
)
from mission_control.runtime.offsite_backup import (
    OffsiteBackupConfig,
    OffsiteBackupConfigurationError,
    fetch_backup_and_verify,
    publish_backup_and_verify,
)


class _MemoryS3:
    def __init__(self, *, tamper_on_read: bool = False) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, dict[str, str]]] = {}
        self.tamper_on_read = tamper_on_read

    def put_object(self, **kwargs):
        body = kwargs["Body"].read()
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = (
            body,
            dict(kwargs["Metadata"]),
        )
        return {"ETag": "not-used-for-integrity"}

    def get_object(self, **kwargs):
        body, metadata = self.objects[(kwargs["Bucket"], kwargs["Key"])]
        if self.tamper_on_read:
            body += b"tampered"
        return {"Body": BytesIO(body), "Metadata": metadata}


def _storage(tmp_path: Path) -> PilotRuntimeStorageConfig:
    state = tmp_path / "state"
    backup = tmp_path / "backup"
    state.mkdir()
    backup.mkdir()
    config = PilotRuntimeStorageConfig(
        state_volume_root=state,
        state_volume_id="state-v1",
        backup_volume_root=backup,
        backup_volume_id="backup-staging-v1",
    )
    bootstrap_pilot_storage(config)
    return config


def _offsite() -> OffsiteBackupConfig:
    return OffsiteBackupConfig(
        bucket="mission-control-pilot",
        prefix="pilot/calendar-state",
        endpoint_url="https://example.r2.cloudflarestorage.com",
    )


def test_offsite_configuration_is_explicit_and_prefix_safe():
    with pytest.raises(OffsiteBackupConfigurationError, match="required"):
        OffsiteBackupConfig.from_environment({})

    with pytest.raises(OffsiteBackupConfigurationError, match="unsafe"):
        OffsiteBackupConfig(bucket="pilot", prefix="pilot/../calendar")


def test_verified_backup_is_uploaded_and_fully_read_back(tmp_path):
    storage = _storage(tmp_path)
    local = create_consistent_backup(storage, backup_name="daily.sqlite3")
    client = _MemoryS3()

    receipt = publish_backup_and_verify(
        storage,
        _offsite(),
        local,
        client=client,
    )

    assert receipt.object_key == "pilot/calendar-state/daily.sqlite3"
    assert receipt.sha256 == local.sha256
    assert receipt.proposal_count == 0
    assert not tuple(storage.backup_directory.glob(".offsite-readback-*"))


def test_offsite_checksum_mismatch_fails_without_verified_receipt(tmp_path):
    storage = _storage(tmp_path)
    local = create_consistent_backup(storage, backup_name="daily.sqlite3")

    with pytest.raises(BackupValidationError, match="checksum"):
        publish_backup_and_verify(
            storage,
            _offsite(),
            local,
            client=_MemoryS3(tamper_on_read=True),
        )

    assert not tuple(storage.backup_directory.glob(".offsite-readback-*"))


def test_offsite_fetch_validates_and_never_overwrites(tmp_path):
    storage = _storage(tmp_path)
    local = create_consistent_backup(storage, backup_name="source.sqlite3")
    client = _MemoryS3()
    published = publish_backup_and_verify(
        storage,
        _offsite(),
        local,
        client=client,
    )
    storage.database_path.unlink()

    fetched = fetch_backup_and_verify(
        storage,
        _offsite(),
        published.object_key,
        local_name="recovery.sqlite3",
        client=client,
    )

    assert fetched.sha256 == local.sha256
    assert fetched.backup_path.name == "recovery.sqlite3"
    with pytest.raises(RuntimeStorageConfigurationError, match="overwrite"):
        fetch_backup_and_verify(
            storage,
            _offsite(),
            published.object_key,
            local_name="recovery.sqlite3",
            client=client,
        )


def test_offsite_fetch_rejects_keys_outside_configured_prefix(tmp_path):
    storage = _storage(tmp_path)

    with pytest.raises(OffsiteBackupConfigurationError, match="outside"):
        fetch_backup_and_verify(
            storage,
            _offsite(),
            "other/calendar-state/daily.sqlite3",
            client=_MemoryS3(),
        )
