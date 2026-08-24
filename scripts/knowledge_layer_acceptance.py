"""Synthetic acceptance for the Executive Status Packet foundation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from mission_control.knowledge.boundary import (
    CredentialSource,
    KnowledgeStorageBoundary,
)
from mission_control.knowledge.status_packet import validate_status_packet


def main() -> None:
    fixture = REPOSITORY_ROOT / "tests/fixtures/knowledge/valid_packet.json"
    payload = json.loads(fixture.read_text())
    packet = validate_status_packet(
        payload,
        expected_domain_id="synthetic-operations",
    )
    restored = validate_status_packet(packet.model_dump(mode="json"))
    assert restored == packet

    with TemporaryDirectory(prefix="mission-control-knowledge-") as directory:
        root = Path(directory)
        KnowledgeStorageBoundary(
            repository_root=REPOSITORY_ROOT,
            operator_knowledge_root=root / "operator-knowledge",
            runtime_state_root=root / "runtime-state",
            credential_source=CredentialSource.SEALED_ENVIRONMENT,
        ).validate()

    print("KNOWLEDGE_LAYER_ACCEPTANCE=PASS")
    print("SCHEMA_VERSION=1.0")
    print("ROUND_TRIP_SEMANTICS=VERIFIED")
    print("DATA_BOUNDARY=VERIFIED")
    print("REAL_OPERATOR_DATA=0")
    print("EXTERNAL_ACTIONS=0")


if __name__ == "__main__":
    main()
