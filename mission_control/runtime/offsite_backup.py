"""Thin S3-compatible offsite backup boundary for the pilot runtime."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Protocol
from uuid import uuid4

from mission_control.capabilities.briefing.persistence import (
    SqliteCalendarProposalStore,
)
from mission_control.runtime.calendar_storage import (
    BackupReceipt,
    BackupValidationError,
    PilotRuntimeStorageConfig,
    RuntimeStorageConfigurationError,
    RuntimeStorageError,
    RuntimeStorageUnavailableError,
    inspect_consistent_backup,
)


class OffsiteBackupError(RuntimeStorageError):
    """The independent object-storage copy could not be verified."""


class OffsiteBackupConfigurationError(OffsiteBackupError):
    """Required object-storage configuration is absent or unsafe."""


class ObjectStorageClient(Protocol):
    """Small subset of the maintained S3 client used by Mission Control."""

    def put_object(self, **kwargs: Any) -> Any: ...

    def get_object(self, **kwargs: Any) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class OffsiteBackupConfig:
    bucket: str
    prefix: str = "mission-control/calendar-state"
    endpoint_url: str | None = None
    region_name: str = "auto"

    def __post_init__(self) -> None:
        bucket = self.bucket.strip()
        prefix = self.prefix.strip().strip("/")
        endpoint = self.endpoint_url.strip() if self.endpoint_url else None
        region = self.region_name.strip()
        if not bucket:
            raise OffsiteBackupConfigurationError(
                "The offsite backup bucket must be explicit."
            )
        if not prefix or prefix in {".", ".."} or "//" in prefix:
            raise OffsiteBackupConfigurationError(
                "The offsite backup prefix must be a non-empty object-key prefix."
            )
        if any(part in {"", ".", ".."} for part in prefix.split("/")):
            raise OffsiteBackupConfigurationError(
                "The offsite backup prefix contains an unsafe path segment."
            )
        if not region:
            raise OffsiteBackupConfigurationError(
                "The object-storage region must be explicit."
            )
        object.__setattr__(self, "bucket", bucket)
        object.__setattr__(self, "prefix", prefix)
        object.__setattr__(self, "endpoint_url", endpoint)
        object.__setattr__(self, "region_name", region)

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "OffsiteBackupConfig":
        values = os.environ if environ is None else environ
        bucket = values.get("MISSION_CONTROL_OFFSITE_BUCKET", "")
        if not bucket.strip():
            raise OffsiteBackupConfigurationError(
                "MISSION_CONTROL_OFFSITE_BUCKET is required."
            )
        return cls(
            bucket=bucket,
            prefix=values.get(
                "MISSION_CONTROL_OFFSITE_PREFIX",
                "mission-control/calendar-state",
            ),
            endpoint_url=values.get("MISSION_CONTROL_OFFSITE_ENDPOINT_URL"),
            region_name=values.get("MISSION_CONTROL_OFFSITE_REGION", "auto"),
        )

    def object_key(self, backup_name: str) -> str:
        if Path(backup_name).name != backup_name or not backup_name.endswith(".sqlite3"):
            raise OffsiteBackupConfigurationError(
                "The offsite object name must be a simple .sqlite3 filename."
            )
        return f"{self.prefix}/{backup_name}"

    def validate_key(self, key: str) -> str:
        expected = f"{self.prefix}/"
        if not key.startswith(expected) or key == expected:
            raise OffsiteBackupConfigurationError(
                "The requested object is outside the configured offsite prefix."
            )
        name = key.removeprefix(expected)
        if Path(name).name != name or not name.endswith(".sqlite3"):
            raise OffsiteBackupConfigurationError(
                "The requested offsite object key is unsafe."
            )
        return name


@dataclass(frozen=True)
class OffsiteBackupReceipt:
    bucket: str
    object_key: str
    verified_at: datetime
    sha256: str
    proposal_count: int
    audit_record_count: int
    receipt_count: int


def create_s3_client(config: OffsiteBackupConfig) -> ObjectStorageClient:
    """Create the commodity S3 client without making it a core dependency."""

    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - deployment dependency gate
        raise OffsiteBackupConfigurationError(
            "boto3 is required for S3-compatible offsite backup operations."
        ) from exc
    return boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        region_name=config.region_name,
    )


def publish_backup_and_verify(
    storage: PilotRuntimeStorageConfig,
    offsite: OffsiteBackupConfig,
    backup: BackupReceipt,
    *,
    client: ObjectStorageClient | None = None,
) -> OffsiteBackupReceipt:
    """Upload one validated backup and fully read it back before success."""

    inspected = inspect_consistent_backup(storage, backup.backup_path)
    if _receipt_semantics(inspected) != _receipt_semantics(backup):
        raise BackupValidationError(
            "The local backup changed before offsite publication."
        )
    key = offsite.object_key(inspected.backup_path.name)
    s3 = client or create_s3_client(offsite)
    metadata = {
        "sha256": inspected.sha256,
        "proposal-count": str(inspected.proposal_count),
        "audit-record-count": str(inspected.audit_record_count),
        "receipt-count": str(inspected.receipt_count),
    }
    try:
        with inspected.backup_path.open("rb") as source:
            s3.put_object(
                Bucket=offsite.bucket,
                Key=key,
                Body=source,
                ContentType="application/vnd.sqlite3",
                Metadata=metadata,
                IfNoneMatch="*",
            )
        downloaded = _read_object_to_partial(
            storage,
            offsite,
            key,
            s3,
            expected_sha256=inspected.sha256,
        )
        try:
            snapshot = SqliteCalendarProposalStore(
                downloaded,
                initialize_if_missing=False,
            ).validate_integrity()
            if (
                len(snapshot.proposals) != inspected.proposal_count
                or len(snapshot.audit_records) != inspected.audit_record_count
                or len(snapshot.receipts) != inspected.receipt_count
            ):
                raise BackupValidationError(
                    "Offsite read-back record counts differ from the local backup."
                )
        finally:
            downloaded.unlink(missing_ok=True)
    except RuntimeStorageError:
        raise
    except Exception as exc:
        raise OffsiteBackupError(
            "S3-compatible publication or read-back failed; no verified offsite "
            "backup receipt was issued."
        ) from exc
    return OffsiteBackupReceipt(
        bucket=offsite.bucket,
        object_key=key,
        verified_at=datetime.now(UTC),
        sha256=inspected.sha256,
        proposal_count=inspected.proposal_count,
        audit_record_count=inspected.audit_record_count,
        receipt_count=inspected.receipt_count,
    )


def fetch_backup_and_verify(
    storage: PilotRuntimeStorageConfig,
    offsite: OffsiteBackupConfig,
    object_key: str,
    *,
    local_name: str | None = None,
    client: ObjectStorageClient | None = None,
) -> BackupReceipt:
    """Fetch an offsite object into local staging and validate before publish."""

    source_name = offsite.validate_key(object_key)
    destination_name = local_name or source_name
    destination = storage.backup_directory / destination_name
    if Path(destination_name).name != destination_name or not destination_name.endswith(
        ".sqlite3"
    ):
        raise OffsiteBackupConfigurationError(
            "The local restore staging name must be a simple .sqlite3 filename."
        )
    if destination.exists() or destination.is_symlink():
        raise RuntimeStorageConfigurationError(
            "Offsite fetch refused to overwrite an existing local backup."
        )
    s3 = client or create_s3_client(offsite)
    partial = _read_object_to_partial(storage, offsite, object_key, s3)
    try:
        os.link(partial, destination)
        partial.unlink()
    except FileExistsError as exc:
        raise RuntimeStorageConfigurationError(
            "Offsite fetch destination appeared and was not overwritten."
        ) from exc
    except OSError as exc:
        raise RuntimeStorageUnavailableError(
            "The verified offsite backup could not be published locally."
        ) from exc
    return inspect_consistent_backup(storage, destination)


def _read_object_to_partial(
    storage: PilotRuntimeStorageConfig,
    offsite: OffsiteBackupConfig,
    key: str,
    client: ObjectStorageClient,
    *,
    expected_sha256: str | None = None,
) -> Path:
    partial = storage.backup_directory / f".offsite-readback-{uuid4().hex}.partial"
    try:
        response = client.get_object(Bucket=offsite.bucket, Key=key)
        metadata = {
            str(name).lower(): str(value)
            for name, value in dict(response.get("Metadata", {})).items()
        }
        declared_sha = metadata.get("sha256")
        if not declared_sha or (expected_sha256 and declared_sha != expected_sha256):
            raise BackupValidationError(
                "Offsite object checksum metadata is absent or does not match."
            )
        body = response["Body"]
        with partial.open("xb") as destination:
            while True:
                block = body.read(1024 * 1024)
                if not block:
                    break
                destination.write(block)
            destination.flush()
            os.fsync(destination.fileno())
        partial.chmod(0o600)
        actual_sha = _sha256(partial)
        if actual_sha != declared_sha:
            raise BackupValidationError(
                "Offsite object failed full checksum read-back verification."
            )
        SqliteCalendarProposalStore(
            partial,
            initialize_if_missing=False,
        ).validate_integrity()
        return partial
    except RuntimeStorageError:
        partial.unlink(missing_ok=True)
        raise
    except Exception as exc:
        partial.unlink(missing_ok=True)
        raise OffsiteBackupError(
            "The offsite backup could not be downloaded and verified."
        ) from exc


def _receipt_semantics(receipt: BackupReceipt) -> tuple[str, int, int, int]:
    return (
        receipt.sha256,
        receipt.proposal_count,
        receipt.audit_record_count,
        receipt.receipt_count,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
