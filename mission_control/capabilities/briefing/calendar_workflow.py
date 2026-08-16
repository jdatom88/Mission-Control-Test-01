"""Governed briefing-to-calendar proposal workflow.

This is the narrow Stage 3 vertical slice. It preserves source context and
approval state without attempting to implement the full briefing engine.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from mission_control.capabilities.calendar.direct import (
    DirectCalendarConnector,
    create_event_with_readback,
)
from mission_control.capabilities.calendar.service import MissionControlEvent, export_ics


class ProposalDecision(str, Enum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"
    DEFER = "defer"


class ProposalStatus(str, Enum):
    PENDING = "pending"
    DEFERRED = "deferred"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FALLBACK_READY = "fallback_ready"
    EXECUTION_FAILED = "execution_failed"


class ExecutionOutcome(str, Enum):
    DIRECT_VERIFIED = "direct_verified"
    ICS_VERIFIED = "ics_verified"
    FAILED = "failed"


class AuditAction(str, Enum):
    PREPARE = "prepare"
    EDIT = "edit"
    APPROVE = "approve"
    REJECT = "reject"
    DEFER = "defer"
    EXECUTE = "execute"


@dataclass(frozen=True)
class SourceItem:
    """Synthetic or retrieved source context that justifies a proposal."""

    source_id: str
    heading: str
    context: str

    def validate(self) -> None:
        if not self.source_id.strip():
            raise ValueError("Source ID is required")
        if not self.heading.strip():
            raise ValueError("Source heading is required")
        if not self.context.strip():
            raise ValueError("Source context is required")


@dataclass(frozen=True)
class CalendarProposal:
    """One displayed proposal version governed by an explicit decision."""

    proposal_id: str
    version: int
    source: SourceItem
    rationale: str
    event: MissionControlEvent
    calendar_id: str = "primary"
    destination_label: str = "Primary calendar"
    assumptions: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    status: ProposalStatus = ProposalStatus.PENDING

    @property
    def operation_id(self) -> str:
        """Stable version-specific ID for duplicate-safe provider retries."""
        source = f"{self.proposal_id}:{self.version}".encode("utf-8")
        return "mc" + sha256(source).hexdigest()[:30]

    def validate(self) -> None:
        if not self.proposal_id.strip():
            raise ValueError("Proposal ID is required")
        if self.version < 1:
            raise ValueError("Proposal version must be positive")
        self.source.validate()
        if not self.rationale.strip():
            raise ValueError("Proposal rationale is required")
        if not self.calendar_id.strip():
            raise ValueError("Destination calendar ID is required")
        if not self.destination_label.strip():
            raise ValueError("Destination calendar label is required")
        self.event.validate()


@dataclass(frozen=True)
class ExecutionReceipt:
    """Truthful external-write or fallback-artifact result."""

    outcome: ExecutionOutcome
    verified: bool
    message: str
    provider: str | None = None
    event_id: str | None = None
    event_url: str | None = None
    artifact_path: Path | None = None


class CalendarProposalExecutor(Protocol):
    def execute(self, proposal: CalendarProposal) -> ExecutionReceipt: ...


class DirectProposalExecutor:
    """Route an approved proposal through provider read-back verification."""

    def __init__(self, connector: DirectCalendarConnector) -> None:
        self._connector = connector

    def execute(self, proposal: CalendarProposal) -> ExecutionReceipt:
        result = create_event_with_readback(
            proposal.event,
            self._connector,
            calendar_id=proposal.calendar_id,
            operation_id=proposal.operation_id,
        )
        if not result.verified:
            return ExecutionReceipt(
                outcome=ExecutionOutcome.FAILED,
                verified=False,
                message=result.message,
                provider=result.provider,
                event_id=result.event_id,
                event_url=result.event_url,
            )
        return ExecutionReceipt(
            outcome=ExecutionOutcome.DIRECT_VERIFIED,
            verified=True,
            message=result.message,
            provider=result.provider,
            event_id=result.event_id,
            event_url=result.event_url,
        )


class IcsProposalExecutor:
    """Generate a verified artifact without claiming provider creation."""

    def __init__(self, output_directory: str | Path) -> None:
        self._output_directory = Path(output_directory)

    def execute(self, proposal: CalendarProposal) -> ExecutionReceipt:
        event = replace(
            proposal.event,
            uid=f"{proposal.operation_id}@mission-control.local",
        )
        artifact = export_ics(
            event,
            self._output_directory / f"{proposal.operation_id}.ics",
        )
        return ExecutionReceipt(
            outcome=ExecutionOutcome.ICS_VERIFIED,
            verified=True,
            message="ICS generated and verified; manual calendar import required.",
            provider="ics",
            artifact_path=artifact,
        )


class DirectWithIcsFallbackExecutor:
    """Prefer verified direct creation and fall back to a verified ICS file."""

    def __init__(
        self,
        direct_executor: CalendarProposalExecutor,
        fallback_executor: CalendarProposalExecutor,
    ) -> None:
        self._direct_executor = direct_executor
        self._fallback_executor = fallback_executor

    def execute(self, proposal: CalendarProposal) -> ExecutionReceipt:
        direct = self._direct_executor.execute(proposal)
        if direct.verified:
            return direct

        fallback = self._fallback_executor.execute(proposal)
        if not fallback.verified:
            return ExecutionReceipt(
                outcome=ExecutionOutcome.FAILED,
                verified=False,
                message=(
                    f"Direct calendar creation was not verified: {direct.message} "
                    f"Fallback also failed: {fallback.message}"
                ),
            )
        return replace(
            fallback,
            message=(
                f"Direct calendar creation was not verified: {direct.message} "
                f"{fallback.message}"
            ),
        )


@dataclass(frozen=True)
class AuditRecord:
    proposal_id: str
    version: int
    action: AuditAction
    status: ProposalStatus
    detail: str
    recorded_at: datetime
    decision: ProposalDecision | None = None
    execution_outcome: ExecutionOutcome | None = None
    verified: bool | None = None


@dataclass(frozen=True)
class DecisionResult:
    proposal: CalendarProposal
    receipt: ExecutionReceipt | None = None


class CalendarProposalWorkflow:
    """In-memory lifecycle for the single Stage 3 briefing vertical slice."""

    def __init__(self) -> None:
        self._proposals: dict[str, CalendarProposal] = {}
        self._audit: list[AuditRecord] = []

    @property
    def audit_history(self) -> tuple[AuditRecord, ...]:
        return tuple(self._audit)

    def get(self, proposal_id: str) -> CalendarProposal:
        try:
            return self._proposals[proposal_id]
        except KeyError as exc:
            raise KeyError(f"Unknown calendar proposal: {proposal_id}") from exc

    def prepare(
        self,
        source: SourceItem,
        event: MissionControlEvent,
        *,
        rationale: str,
        proposal_id: str | None = None,
        calendar_id: str = "primary",
        destination_label: str = "Primary calendar",
        assumptions: tuple[str, ...] = (),
        conflicts: tuple[str, ...] = (),
    ) -> CalendarProposal:
        proposal = CalendarProposal(
            proposal_id=proposal_id or f"proposal-{uuid4().hex}",
            version=1,
            source=source,
            rationale=rationale,
            event=event,
            calendar_id=calendar_id,
            destination_label=destination_label,
            assumptions=assumptions,
            conflicts=conflicts,
        )
        proposal.validate()
        if proposal.proposal_id in self._proposals:
            raise ValueError("Proposal ID already exists")
        self._proposals[proposal.proposal_id] = proposal
        self._record(proposal, AuditAction.PREPARE, "Proposal prepared; approval pending.")
        return proposal

    def edit(
        self,
        proposal_id: str,
        revised_event: MissionControlEvent,
        *,
        rationale: str | None = None,
        calendar_id: str | None = None,
        destination_label: str | None = None,
        assumptions: tuple[str, ...] | None = None,
        conflicts: tuple[str, ...] | None = None,
    ) -> DecisionResult:
        current = self._require_decidable(proposal_id)
        revised = replace(
            current,
            version=current.version + 1,
            event=revised_event,
            rationale=rationale if rationale is not None else current.rationale,
            calendar_id=calendar_id if calendar_id is not None else current.calendar_id,
            destination_label=(
                destination_label
                if destination_label is not None
                else current.destination_label
            ),
            assumptions=assumptions if assumptions is not None else current.assumptions,
            conflicts=conflicts if conflicts is not None else current.conflicts,
            status=ProposalStatus.PENDING,
        )
        revised.validate()
        self._proposals[proposal_id] = revised
        self._record(
            revised,
            AuditAction.EDIT,
            "Proposal revised; the displayed new version requires renewed approval.",
            decision=ProposalDecision.EDIT,
        )
        return DecisionResult(revised)

    def approve(
        self,
        proposal_id: str,
        executor: CalendarProposalExecutor,
    ) -> DecisionResult:
        proposal = self._require_decidable(proposal_id)
        self._record(
            proposal,
            AuditAction.APPROVE,
            "Displayed proposal version approved for one governed execution.",
            decision=ProposalDecision.APPROVE,
        )
        try:
            receipt = executor.execute(proposal)
        except Exception as exc:
            receipt = ExecutionReceipt(
                outcome=ExecutionOutcome.FAILED,
                verified=False,
                message=f"Calendar execution failed: {exc}",
            )

        if receipt.outcome is ExecutionOutcome.DIRECT_VERIFIED and receipt.verified:
            status = ProposalStatus.EXECUTED
        elif receipt.outcome is ExecutionOutcome.ICS_VERIFIED and receipt.verified:
            status = ProposalStatus.FALLBACK_READY
        else:
            status = ProposalStatus.EXECUTION_FAILED

        completed = replace(proposal, status=status)
        self._proposals[proposal_id] = completed
        self._record(
            completed,
            AuditAction.EXECUTE,
            receipt.message,
            execution_outcome=receipt.outcome,
            verified=receipt.verified,
        )
        return DecisionResult(completed, receipt)

    def reject(self, proposal_id: str) -> DecisionResult:
        proposal = replace(
            self._require_decidable(proposal_id),
            status=ProposalStatus.REJECTED,
        )
        self._proposals[proposal_id] = proposal
        self._record(
            proposal,
            AuditAction.REJECT,
            "Proposal rejected; no execution occurred.",
            decision=ProposalDecision.REJECT,
        )
        return DecisionResult(proposal)

    def defer(self, proposal_id: str) -> DecisionResult:
        proposal = replace(
            self._require_decidable(proposal_id),
            status=ProposalStatus.DEFERRED,
        )
        self._proposals[proposal_id] = proposal
        self._record(
            proposal,
            AuditAction.DEFER,
            "Proposal deferred; it remains eligible for a later approval queue.",
            decision=ProposalDecision.DEFER,
        )
        return DecisionResult(proposal)

    def active_queue(self) -> tuple[CalendarProposal, ...]:
        return tuple(
            proposal
            for proposal in self._proposals.values()
            if proposal.status in {ProposalStatus.PENDING, ProposalStatus.DEFERRED}
        )

    def render_inline(self, proposal_id: str) -> str:
        proposal = self.get(proposal_id)
        return "\n".join(
            [
                "[Calendar proposal — awaiting decision]",
                f"Proposal: {proposal.event.title}",
                f"When: {_event_time(proposal.event)}",
                f"Destination: {proposal.destination_label}",
                f"Why it matters: {proposal.rationale}",
                f"Source: {proposal.source.heading} ({proposal.source.source_id})",
                f"Source context: {proposal.source.context}",
                f"Assumptions: {_list_text(proposal.assumptions)}",
                f"Conflicts: {_list_text(proposal.conflicts)}",
                f"Status: {proposal.status.value}; version {proposal.version}",
            ]
        )

    def render_queue(self, *, final: bool = False) -> str:
        proposals = self.active_queue()
        heading = "Final Calendar Approval Queue" if final else "Calendar Approval Queue"
        if not proposals:
            return f"{heading}\nNo pending calendar proposals."

        lines = [heading]
        for index, proposal in enumerate(proposals, start=1):
            lines.extend(
                [
                    "",
                    f"{index}. {proposal.event.title} — {_event_time(proposal.event)}",
                    f"   Why: {proposal.rationale}",
                    f"   Source: {proposal.source.heading} ({proposal.source.source_id})",
                    f"   Context: {proposal.source.context}",
                    f"   Destination: {proposal.destination_label}",
                    f"   Version: {proposal.version}; status: {proposal.status.value}",
                    "   Decision: Approve | Edit | Reject | Defer",
                ]
            )
        return "\n".join(lines)

    def _require_decidable(self, proposal_id: str) -> CalendarProposal:
        proposal = self.get(proposal_id)
        if proposal.status not in {ProposalStatus.PENDING, ProposalStatus.DEFERRED}:
            raise ValueError(
                f"Proposal {proposal_id} cannot be decided from status "
                f"{proposal.status.value}"
            )
        return proposal

    def _record(
        self,
        proposal: CalendarProposal,
        action: AuditAction,
        detail: str,
        *,
        decision: ProposalDecision | None = None,
        execution_outcome: ExecutionOutcome | None = None,
        verified: bool | None = None,
    ) -> None:
        self._audit.append(
            AuditRecord(
                proposal_id=proposal.proposal_id,
                version=proposal.version,
                action=action,
                status=proposal.status,
                detail=detail,
                recorded_at=datetime.now(timezone.utc),
                decision=decision,
                execution_outcome=execution_outcome,
                verified=verified,
            )
        )


def _event_time(event: MissionControlEvent) -> str:
    return f"{event.start.isoformat()} to {event.end.isoformat()}"


def _list_text(items: tuple[str, ...]) -> str:
    return "; ".join(items) if items else "None"
