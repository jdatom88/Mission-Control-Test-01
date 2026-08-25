"""Run the Stage 5 durability acceptance guardian; not a briefing API."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from mission_control.runtime.calendar_storage import (
    PilotRuntimeStorageConfig,
    RuntimeStorageError,
)
from mission_control.runtime.offsite_backup import OffsiteBackupConfig
from mission_control.runtime.pilot_guardian import (
    PilotGuardianConfig,
    PilotStorageGuardian,
)
from mission_control.security.config import SecurityBoundaryConfig
from mission_control.security.errors import (
    SecurityBoundaryError,
    SecurityConfigurationError,
)
from mission_control.security.google_oauth import GoogleOAuthProvider
from mission_control.security.http_adapter import SecurityHttpAdapter
from mission_control.security.service import open_security_boundary


def main() -> None:
    try:
        runtime = PilotGuardianConfig.from_environment()
        guardian = PilotStorageGuardian(
            PilotRuntimeStorageConfig.from_environment(),
            OffsiteBackupConfig.from_environment(),
            runtime,
        )
        print(
            json.dumps(
                {
                    "operation": "pilot-storage-guardian",
                    "status": "starting",
                    "port": runtime.port,
                    "backup_interval_seconds": runtime.backup_interval_seconds,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        route_handler = _security_route_handler()
        guardian.serve(route_handler=route_handler)
    except (RuntimeStorageError, SecurityBoundaryError) as exc:
        print(f"PILOT_RUNTIME_ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(2) from exc


def _security_route_handler():
    enabled = (
        os.environ.get("MISSION_CONTROL_SECURITY_HTTP_ENABLED", "false")
        .strip()
        .lower()
    )
    if enabled not in {"true", "false"}:
        raise SecurityConfigurationError(
            "MISSION_CONTROL_SECURITY_HTTP_ENABLED must be true or false."
        )
    if enabled == "false":
        return None
    config = SecurityBoundaryConfig.from_environment(repository_root=REPOSITORY_ROOT)
    boundary = open_security_boundary(config)
    provider = GoogleOAuthProvider(
        client_id=config.google_oauth_client_id,
        client_secret=config.google_oauth_client_secret,
        redirect_uri=config.google_oauth_redirect_uri,
    )
    return SecurityHttpAdapter(boundary, provider, config.google_oauth_redirect_uri)


if __name__ == "__main__":
    main()
