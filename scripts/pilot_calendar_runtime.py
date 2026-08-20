"""Run the Stage 5 durability acceptance guardian; not a briefing API."""

from __future__ import annotations

import json
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
        guardian.serve()
    except RuntimeStorageError as exc:
        print(f"PILOT_RUNTIME_ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
