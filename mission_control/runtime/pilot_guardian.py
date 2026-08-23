"""Fail-loud single-instance storage guardian for deployed pilot acceptance."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Mapping

from mission_control.runtime.calendar_storage import (
    PilotRuntimeStorageConfig,
    RuntimeStorageConfigurationError,
    RuntimeStorageUnavailableError,
    create_consistent_backup,
    open_pilot_store,
)
from mission_control.runtime.offsite_backup import (
    OffsiteBackupConfig,
    publish_backup_and_verify,
)


@dataclass(frozen=True)
class PilotGuardianConfig:
    port: int = 8080
    storage_check_seconds: int = 60
    backup_interval_seconds: int = 86_400
    backup_on_start: bool = False

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "PilotGuardianConfig":
        values = os.environ if environ is None else environ
        try:
            port = int(values.get("PORT", "8080"))
            check_seconds = int(
                values.get("MISSION_CONTROL_STORAGE_CHECK_SECONDS", "60")
            )
            backup_seconds = int(
                values.get("MISSION_CONTROL_BACKUP_INTERVAL_SECONDS", "86400")
            )
        except ValueError as exc:
            raise RuntimeStorageConfigurationError(
                "Guardian port and intervals must be whole numbers."
            ) from exc
        if not 1 <= port <= 65_535:
            raise RuntimeStorageConfigurationError(
                "Guardian PORT must be between 1 and 65535."
            )
        if check_seconds < 5:
            raise RuntimeStorageConfigurationError(
                "Storage checks may not be less than five seconds apart."
            )
        if backup_seconds < 300:
            raise RuntimeStorageConfigurationError(
                "Verified offsite backups may not be scheduled less than five "
                "minutes apart."
            )
        backup_on_start = values.get(
            "MISSION_CONTROL_BACKUP_ON_START", "false"
        ).strip().lower()
        if backup_on_start not in {"true", "false"}:
            raise RuntimeStorageConfigurationError(
                "MISSION_CONTROL_BACKUP_ON_START must be true or false."
            )
        return cls(
            port=port,
            storage_check_seconds=check_seconds,
            backup_interval_seconds=backup_seconds,
            backup_on_start=backup_on_start == "true",
        )


class PilotStorageGuardian:
    """Own storage checks and scheduled verified offsite backups."""

    def __init__(
        self,
        storage: PilotRuntimeStorageConfig,
        offsite: OffsiteBackupConfig,
        runtime: PilotGuardianConfig,
    ) -> None:
        self.storage = storage
        self.offsite = offsite
        self.runtime = runtime
        self.last_backup: dict[str, object] | None = None

    def check_payload(self) -> dict[str, object]:
        snapshot = open_pilot_store(self.storage).validate_integrity()
        return {
            "status": "healthy",
            "storage": "verified",
            "proposal_count": len(snapshot.proposals),
            "audit_record_count": len(snapshot.audit_records),
            "receipt_count": len(snapshot.receipts),
            "last_backup": self.last_backup,
        }

    def backup(self) -> dict[str, object]:
        local = create_consistent_backup(self.storage)
        receipt = publish_backup_and_verify(self.storage, self.offsite, local)
        try:
            local.backup_path.unlink()
        except OSError as exc:
            raise RuntimeStorageUnavailableError(
                "The verified local staging backup could not be removed."
            ) from exc
        self.last_backup = {
            "bucket": receipt.bucket,
            "object_key": receipt.object_key,
            "verified_at": receipt.verified_at.isoformat(),
            "sha256": receipt.sha256,
        }
        return self.last_backup

    def serve(self) -> None:
        self.check_payload()
        if self.runtime.backup_on_start:
            self.backup()
        guardian = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path != "/healthz":
                    self.send_error(404)
                    return
                try:
                    payload = guardian.check_payload()
                    status = 200
                except Exception as exc:
                    payload = {"status": "unhealthy", "error": str(exc)}
                    status = 503
                body = json.dumps(payload, sort_keys=True).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("0.0.0.0", self.runtime.port), Handler)
        server.timeout = 1
        next_check = time.monotonic() + self.runtime.storage_check_seconds
        next_backup = time.monotonic() + self.runtime.backup_interval_seconds
        try:
            while True:
                server.handle_request()
                now = time.monotonic()
                if now >= next_check:
                    self.check_payload()
                    next_check = now + self.runtime.storage_check_seconds
                if now >= next_backup:
                    self.backup()
                    next_backup = now + self.runtime.backup_interval_seconds
        finally:
            server.server_close()
