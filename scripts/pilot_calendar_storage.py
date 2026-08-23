"""Operate the Mission Control pilot calendar-state durability boundary."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from mission_control.runtime.calendar_storage import (
    PilotRuntimeStorageConfig,
    RuntimeStorageError,
    bootstrap_pilot_storage,
    create_consistent_backup,
    open_pilot_store,
    restore_consistent_backup,
)
from mission_control.runtime.offsite_backup import (
    OffsiteBackupConfig,
    fetch_backup_and_verify,
    publish_backup_and_verify,
)


def _snapshot_payload(store) -> dict[str, object]:
    snapshot = store.validate_integrity()
    return {
        "status": "verified",
        "database_path": str(store.database_path),
        "proposal_count": len(snapshot.proposals),
        "audit_record_count": len(snapshot.audit_records),
        "receipt_count": len(snapshot.receipts),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Bootstrap, verify, back up, or restore the marked pilot "
            "calendar-state volumes. Configuration is read from the required "
            "MISSION_CONTROL_*_VOLUME_* environment variables."
        )
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("bootstrap")
    subcommands.add_parser("check")
    backup = subcommands.add_parser("backup")
    backup.add_argument("--name")
    offsite_backup = subcommands.add_parser("backup-offsite")
    offsite_backup.add_argument("--name")
    fetch = subcommands.add_parser("fetch-offsite")
    fetch.add_argument("object_key")
    fetch.add_argument("--name")
    restore = subcommands.add_parser("restore")
    restore.add_argument("backup_path", type=Path)
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    try:
        config = PilotRuntimeStorageConfig.from_environment()
        if arguments.command == "bootstrap":
            payload = _snapshot_payload(bootstrap_pilot_storage(config))
            payload["operation"] = "bootstrap"
        elif arguments.command == "check":
            payload = _snapshot_payload(open_pilot_store(config))
            payload["operation"] = "check"
        elif arguments.command == "backup":
            receipt = create_consistent_backup(config, backup_name=arguments.name)
            payload = {
                "operation": "backup",
                "status": "verified",
                "backup_path": str(receipt.backup_path),
                "created_at": receipt.created_at.isoformat(),
                "sha256": receipt.sha256,
                "proposal_count": receipt.proposal_count,
                "audit_record_count": receipt.audit_record_count,
                "receipt_count": receipt.receipt_count,
            }
        elif arguments.command == "backup-offsite":
            local = create_consistent_backup(config, backup_name=arguments.name)
            receipt = publish_backup_and_verify(
                config,
                OffsiteBackupConfig.from_environment(),
                local,
            )
            payload = {
                "operation": "backup-offsite",
                "status": "verified",
                "bucket": receipt.bucket,
                "object_key": receipt.object_key,
                "verified_at": receipt.verified_at.isoformat(),
                "sha256": receipt.sha256,
                "proposal_count": receipt.proposal_count,
                "audit_record_count": receipt.audit_record_count,
                "receipt_count": receipt.receipt_count,
            }
        elif arguments.command == "fetch-offsite":
            receipt = fetch_backup_and_verify(
                config,
                OffsiteBackupConfig.from_environment(),
                arguments.object_key,
                local_name=arguments.name,
            )
            payload = {
                "operation": "fetch-offsite",
                "status": "verified",
                "backup_path": str(receipt.backup_path),
                "sha256": receipt.sha256,
                "proposal_count": receipt.proposal_count,
                "audit_record_count": receipt.audit_record_count,
                "receipt_count": receipt.receipt_count,
            }
        else:
            receipt = restore_consistent_backup(config, arguments.backup_path)
            payload = {
                "operation": "restore",
                "status": "verified",
                "restored_database_path": str(receipt.restored_database_path),
                "source_backup_path": str(receipt.source_backup_path),
                "restored_at": receipt.restored_at.isoformat(),
                "sha256": receipt.sha256,
                "proposal_count": receipt.proposal_count,
                "audit_record_count": receipt.audit_record_count,
                "receipt_count": receipt.receipt_count,
            }
    except RuntimeStorageError as exc:
        print(f"PILOT_STORAGE_ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
