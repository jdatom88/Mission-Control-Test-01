"""Versioned Executive Status Packet contract for the Knowledge Layer."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)


SCHEMA_VERSION = "1.0"
PACKET_KIND = "mission_control.executive_status"

NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
]
Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]*$",
    ),
]
Confidence = Annotated[StrictFloat, Field(ge=0.0, le=1.0)]


class LifecycleStatus(str, Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    AT_RISK = "at_risk"
    BLOCKED = "blocked"
    PAUSED = "paused"
    COMPLETE = "complete"
    ARCHIVED = "archived"


class AssertionClassification(str, Enum):
    FACT = "fact"
    ASSUMPTION = "assumption"
    INFERENCE = "inference"
    PREDICTION = "prediction"
    RECOMMENDATION = "recommendation"


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETE = "complete"


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class DomainIdentity(StrictModel):
    domain_id: Identifier
    domain_name: NonEmptyText
    project_id: Identifier | None = None
    project_name: NonEmptyText | None = None


class ProvenanceRecord(StrictModel):
    provenance_id: Identifier
    source_identity: NonEmptyText
    source_reference: NonEmptyText | None = None
    observed_at: AwareDatetime
    classification: AssertionClassification
    confidence: Confidence
    rationale: NonEmptyText


class StatusEntry(StrictModel):
    entry_id: Identifier
    statement: NonEmptyText
    provenance_ids: tuple[Identifier, ...] = ()


class ActiveTask(StrictModel):
    task_id: Identifier
    title: NonEmptyText
    status: TaskStatus
    due_at: AwareDatetime | None = None
    provenance_ids: tuple[Identifier, ...] = ()


class PendingDecision(StrictModel):
    decision_id: Identifier
    question: NonEmptyText
    consequence: NonEmptyText
    needed_by: AwareDatetime | None = None
    provenance_ids: tuple[Identifier, ...] = ()


class ExecutiveStatusPacket(StrictModel):
    """Canonical v1 Knowledge Layer packet shared by Mission Control domains."""

    packet_kind: Literal[PACKET_KIND]
    schema_version: Literal[SCHEMA_VERSION]
    packet_id: Identifier
    identity: DomainIdentity
    lifecycle_status: LifecycleStatus
    last_updated: AwareDatetime
    current_focus: NonEmptyText
    recent_progress: tuple[StatusEntry, ...]
    risks: tuple[StatusEntry, ...]
    opportunities: tuple[StatusEntry, ...]
    active_tasks: tuple[ActiveTask, ...]
    pending_decisions: tuple[PendingDecision, ...]
    next_milestone: NonEmptyText
    confidence: Confidence
    provenance: tuple[ProvenanceRecord, ...]

    @field_validator("last_updated")
    @classmethod
    def require_timezone_offset(cls, value: AwareDatetime) -> AwareDatetime:
        if value.utcoffset() is None:
            raise ValueError("must include an explicit timezone offset")
        return value

    @model_validator(mode="after")
    def validate_references(self) -> "ExecutiveStatusPacket":
        provenance_ids = [item.provenance_id for item in self.provenance]
        if len(provenance_ids) != len(set(provenance_ids)):
            raise ValueError("provenance IDs must be unique")

        known = set(provenance_ids)
        missing: set[str] = set()
        entries: tuple[StatusEntry | ActiveTask | PendingDecision, ...] = (
            *self.recent_progress,
            *self.risks,
            *self.opportunities,
            *self.active_tasks,
            *self.pending_decisions,
        )
        for entry in entries:
            missing.update(set(entry.provenance_ids) - known)
        if missing:
            raise ValueError(
                "unknown provenance reference(s): " + ", ".join(sorted(missing))
            )
        return self


class KnowledgePacketValidationError(ValueError):
    """Fail-loud packet error with stable, field-specific messages."""

    def __init__(self, problems: tuple[str, ...]) -> None:
        self.problems = problems
        super().__init__("Executive Status Packet validation failed: " + "; ".join(problems))


def _format_validation_error(error: ValidationError) -> tuple[str, ...]:
    problems: list[str] = []
    for detail in error.errors(include_url=False, include_context=False):
        location = ".".join(str(part) for part in detail["loc"]) or "packet"
        problems.append(f"{location}: {detail['msg']}")
    return tuple(problems)


def validate_status_packet(
    payload: Any,
    *,
    expected_domain_id: str | None = None,
) -> ExecutiveStatusPacket:
    """Validate one untrusted packet without silently coercing versions/domains."""

    if not isinstance(payload, dict):
        raise KnowledgePacketValidationError(("packet: must be a JSON object",))

    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise KnowledgePacketValidationError(
            (
                "schema_version: unsupported version "
                f"{version!r}; expected {SCHEMA_VERSION!r}",
            )
        )

    try:
        packet = ExecutiveStatusPacket.model_validate(payload)
    except ValidationError as error:
        raise KnowledgePacketValidationError(_format_validation_error(error)) from error

    if expected_domain_id is not None and packet.identity.domain_id != expected_domain_id:
        raise KnowledgePacketValidationError(
            (
                "identity.domain_id: foreign domain "
                f"{packet.identity.domain_id!r}; expected {expected_domain_id!r}",
            )
        )
    return packet


def status_packet_json_schema() -> dict[str, Any]:
    """Return the machine-readable JSON Schema for the canonical packet."""

    return ExecutiveStatusPacket.model_json_schema()
