"""Thin runtime assembly for Mission Control's Tested calendar boundaries.

This module does not implement a briefing engine. It composes the existing
governed calendar read and proposal workflow so one caller can retrieve current
calendar context, render reinforced proposals, and apply durable decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from mission_control.capabilities.briefing.calendar_retrieval import (
    retrieve_calendar_for_briefing,
)
from mission_control.capabilities.briefing.calendar_workflow import (
    CalendarProposal,
    CalendarProposalExecutor,
    CalendarProposalWorkflow,
    DecisionResult,
    SourceItem,
)
from mission_control.capabilities.calendar.read import (
    CalendarReadConnector,
    CalendarReadEvent,
    CalendarReadResult,
)
from mission_control.capabilities.calendar.service import MissionControlEvent
from mission_control.core.connector_state import ConnectorState


@dataclass(frozen=True)
class CalendarRuntimeResult:
    """One fresh briefing-facing calendar assembly result."""

    calendar_read: CalendarReadResult
    calendar_context: str
    inline_proposals: tuple[str, ...]
    approval_queue: str


class CalendarRuntimeAssembly:
    """Compose read, presentation, decision, execution, and persistence seams."""

    def __init__(
        self,
        workflow: CalendarProposalWorkflow,
        connector: CalendarReadConnector | None,
    ) -> None:
        self._workflow = workflow
        self._connector = connector

    @property
    def workflow(self) -> CalendarProposalWorkflow:
        return self._workflow

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
        """Prepare through the existing governed workflow without executing."""
        return self._workflow.prepare(
            source,
            event,
            rationale=rationale,
            proposal_id=proposal_id,
            calendar_id=calendar_id,
            destination_label=destination_label,
            assumptions=assumptions,
            conflicts=conflicts,
        )

    def assemble(
        self,
        *,
        time_min: datetime,
        time_max: datetime,
        calendar_id: str = "primary",
        timezone_name: str | None = None,
        final_queue: bool = False,
    ) -> CalendarRuntimeResult:
        """Perform a fresh read and render the current durable proposal queue."""
        calendar_read = retrieve_calendar_for_briefing(
            self._connector,
            time_min=time_min,
            time_max=time_max,
            calendar_id=calendar_id,
            timezone_name=timezone_name,
        )
        active = self._workflow.active_queue()
        return CalendarRuntimeResult(
            calendar_read=calendar_read,
            calendar_context=_render_calendar_context(calendar_read),
            inline_proposals=tuple(
                self._workflow.render_inline(proposal.proposal_id)
                for proposal in active
            ),
            approval_queue=self._workflow.render_queue(final=final_queue),
        )

    def approve(
        self,
        proposal_id: str,
        executor: CalendarProposalExecutor,
    ) -> DecisionResult:
        return self._workflow.approve(proposal_id, executor)

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
        return self._workflow.edit(
            proposal_id,
            revised_event,
            rationale=rationale,
            calendar_id=calendar_id,
            destination_label=destination_label,
            assumptions=assumptions,
            conflicts=conflicts,
        )

    def reject(self, proposal_id: str) -> DecisionResult:
        return self._workflow.reject(proposal_id)

    def defer(self, proposal_id: str) -> DecisionResult:
        return self._workflow.defer(proposal_id)

    def recover_interrupted(
        self,
        proposal_id: str,
        executor: CalendarProposalExecutor,
    ) -> DecisionResult:
        return self._workflow.recover_interrupted(proposal_id, executor)


def _render_calendar_context(result: CalendarReadResult) -> str:
    lines = [
        "Calendar Context",
        f"Window: {result.time_min.isoformat()} to {result.time_max.isoformat()}",
        f"Status: {result.message}",
    ]
    if result.state is ConnectorState.HEALTHY_DATA_FOUND:
        for event in result.events:
            lines.append(f"- {event.title} — {_event_time(event)}")
    return "\n".join(lines)


def _event_time(event: CalendarReadEvent) -> str:
    if event.all_day:
        return f"all day {event.start.isoformat()} to {event.end.isoformat()}"
    if not isinstance(event.start, datetime) or not isinstance(event.end, datetime):
        raise ValueError("Timed calendar read events require datetime bounds.")
    timezone_label = f" ({event.timezone_name})" if event.timezone_name else ""
    return f"{event.start.isoformat()} to {event.end.isoformat()}{timezone_label}"
