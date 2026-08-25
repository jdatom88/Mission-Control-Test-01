"""Explicit bootstrap and structural checks for Generation 1 security stores."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from mission_control.security.config import SecurityBoundaryConfig
from mission_control.security.errors import (
    AuthenticationRejectedError,
    SecurityBoundaryError,
)
from mission_control.security.service import (
    bootstrap_security_boundary,
    open_security_boundary,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("bootstrap", "check"))
    args = parser.parse_args()
    try:
        config = SecurityBoundaryConfig.from_environment(
            repository_root=REPOSITORY_ROOT
        )
        if args.operation == "bootstrap":
            boundary = bootstrap_security_boundary(config)
        else:
            boundary = open_security_boundary(config)
        boundary.credential_vault.validate_integrity()
        boundary.runtime_store.validate_database_integrity()
        print(
            json.dumps(
                {
                    "operation": args.operation,
                    "status": "verified",
                    "stores": ["provider-credentials", "security-runtime"],
                    "operator_enrolled": _operator_enrolled(boundary),
                },
                sort_keys=True,
            )
        )
    except SecurityBoundaryError as exc:
        print(f"SECURITY_BOUNDARY_ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def _operator_enrolled(boundary) -> bool:
    try:
        boundary.runtime_store.load_operator()
        return True
    except AuthenticationRejectedError:
        return False


if __name__ == "__main__":
    main()
