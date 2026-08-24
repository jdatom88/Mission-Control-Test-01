import json
from pathlib import Path

import pytest

from mission_control.knowledge.boundary import (
    CredentialSource,
    KnowledgeBoundaryError,
    KnowledgeStorageBoundary,
)
from mission_control.knowledge.status_packet import (
    AssertionClassification,
    KnowledgePacketValidationError,
    status_packet_json_schema,
    validate_status_packet,
)


FIXTURES = Path(__file__).parent / "fixtures" / "knowledge"


def _fixture(name):
    return json.loads((FIXTURES / name).read_text())


def test_valid_packet_round_trips_without_semantic_loss():
    payload = _fixture("valid_packet.json")
    packet = validate_status_packet(payload, expected_domain_id="synthetic-operations")

    restored = validate_status_packet(packet.model_dump(mode="json"))

    assert restored == packet
    assert restored.model_dump(mode="json") == payload


def test_incomplete_packet_has_field_specific_errors():
    with pytest.raises(KnowledgePacketValidationError) as captured:
        validate_status_packet(_fixture("incomplete_packet.json"))

    assert "identity: Field required" in str(captured.value)
    assert "next_milestone: Field required" in str(captured.value)


def test_malformed_packet_fails_multiple_invalid_fields():
    with pytest.raises(KnowledgePacketValidationError) as captured:
        validate_status_packet(_fixture("malformed_packet.json"))

    message = str(captured.value)
    assert "identity" in message
    assert "lifecycle_status" in message
    assert "last_updated" in message
    assert "confidence" in message


def test_incompatible_version_fails_before_partial_loading():
    with pytest.raises(KnowledgePacketValidationError, match="unsupported version '2.0'"):
        validate_status_packet(_fixture("incompatible_packet.json"))


def test_foreign_domain_fails_loudly():
    with pytest.raises(KnowledgePacketValidationError, match="foreign domain"):
        validate_status_packet(
            _fixture("foreign_packet.json"),
            expected_domain_id="synthetic-operations",
        )


def test_non_object_packet_fails_loudly():
    with pytest.raises(KnowledgePacketValidationError, match="must be a JSON object"):
        validate_status_packet([])


def test_unknown_fields_are_not_silently_discarded():
    payload = _fixture("valid_packet.json")
    payload["future_field"] = "must require a new schema decision"
    with pytest.raises(KnowledgePacketValidationError, match="future_field"):
        validate_status_packet(payload)


def test_naive_timestamp_fails_loudly():
    payload = _fixture("valid_packet.json")
    payload["last_updated"] = "2026-08-24T09:30:00"
    with pytest.raises(KnowledgePacketValidationError, match="last_updated"):
        validate_status_packet(payload)


def test_string_confidence_is_not_silently_coerced():
    payload = _fixture("valid_packet.json")
    payload["confidence"] = "0.9"
    with pytest.raises(KnowledgePacketValidationError, match="confidence"):
        validate_status_packet(payload)


def test_broken_provenance_reference_fails_loudly():
    payload = _fixture("valid_packet.json")
    payload["risks"] = [
        {
            "entry_id": "risk-001",
            "statement": "A synthetic risk.",
            "provenance_ids": ["missing-source"],
        }
    ]
    with pytest.raises(KnowledgePacketValidationError, match="missing-source"):
        validate_status_packet(payload)


def test_all_required_assertion_classifications_are_supported():
    assert {item.value for item in AssertionClassification} == {
        "fact",
        "assumption",
        "inference",
        "prediction",
        "recommendation",
    }


def test_json_schema_identifies_canonical_packet_and_required_fields():
    schema = status_packet_json_schema()
    assert schema["title"] == "ExecutiveStatusPacket"
    assert "schema_version" in schema["required"]
    assert "pending_decisions" in schema["required"]
    assert schema["additionalProperties"] is False


def test_storage_boundary_accepts_separate_external_roots(tmp_path):
    repository = tmp_path / "repo"
    boundary = KnowledgeStorageBoundary(
        repository_root=repository,
        operator_knowledge_root=tmp_path / "private-knowledge",
        runtime_state_root=tmp_path / "runtime-state",
        credential_source=CredentialSource.SEALED_ENVIRONMENT,
    )
    boundary.validate()


def test_storage_boundary_rejects_operator_data_inside_repository(tmp_path):
    boundary = KnowledgeStorageBoundary(
        repository_root=tmp_path / "repo",
        operator_knowledge_root=tmp_path / "repo" / "operator-data",
        runtime_state_root=tmp_path / "runtime-state",
        credential_source=CredentialSource.SEALED_ENVIRONMENT,
    )
    with pytest.raises(KnowledgeBoundaryError, match="outside the product repository"):
        boundary.validate()


def test_storage_boundary_rejects_nested_knowledge_and_runtime_roots(tmp_path):
    boundary = KnowledgeStorageBoundary(
        repository_root=tmp_path / "repo",
        operator_knowledge_root=tmp_path / "private",
        runtime_state_root=tmp_path / "private" / "state",
        credential_source=CredentialSource.ENCRYPTED_RUNTIME_STORE,
    )
    with pytest.raises(KnowledgeBoundaryError, match="distinct, non-nested"):
        boundary.validate()
