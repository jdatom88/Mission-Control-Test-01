"""Durable state adapter for governed briefing-calendar proposals.

SQLite is an implementation detail behind the CalendarProposalStore protocol.
The workflow owns approval and recovery semantics; this adapter owns atomic,
inspectable persistence only.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mission_control.capabilities.briefing.calendar_workflow import (
    AuditAction,
    AuditRecord,
    CalendarProposal,
    ExecutionOutcome,
    ExecutionReceipt,
    ProposalCheckpoint,
    ProposalDecision,
    ProposalStatus,
    SourceItem,
    StoredExecutionReceipt,
    WorkflowSnapshot,
)
from mission_control.capabilities.calendar.service import MissionControlEvent


SCHEMA_VERSION = 1


class PersistenceError(RuntimeError):
    """Durable workflow state could not be read or written safely."""


class PersistenceConflictError(PersistenceError):
    """Stored state changed after this workflow instance loaded it."""


class PersistenceCorruptionError(PersistenceError):
    """Stored state exists but cannot be interpreted safely."""


class PersistenceCompatibilityError(PersistenceError):
    """Stored state uses an unsupported schema or foreign layout."""


class SqliteCalendarProposalStore:
    """Atomic local persistence for the Stage 4 solo-operator slice."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self._initialize()

    def load(self) -> WorkflowSnapshot:
        try:
            with self._connect() as connection:
                proposals = tuple(
                    self._proposal_from_row(row)
                    for row in connection.execute(
                        "SELECT * FROM proposals ORDER BY created_at, proposal_id"
                    )
                )
                audit_records = tuple(
                    self._audit_from_row(row)
                    for row in connection.execute(
                        "SELECT * FROM audit_records ORDER BY audit_id"
                    )
                )
                receipts = tuple(
                    self._receipt_from_row(row)
                    for row in connection.execute(
                        "SELECT * FROM execution_receipts "
                        "ORDER BY proposal_id, version"
                    )
                )
                self._validate_snapshot(proposals, audit_records, receipts)
        except PersistenceError:
            raise
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            raise PersistenceCorruptionError(
                "Persistent calendar workflow state is unavailable or corrupt."
            ) from exc

        return WorkflowSnapshot(proposals, audit_records, receipts)

    @staticmethod
    def _validate_snapshot(
        proposals: tuple[CalendarProposal, ...],
        audit_records: tuple[AuditRecord, ...],
        receipts: tuple[StoredExecutionReceipt, ...],
    ) -> None:
        proposal_by_id = {proposal.proposal_id: proposal for proposal in proposals}
        if len(proposal_by_id) != len(proposals):
            raise PersistenceCorruptionError(
                "Persistent calendar workflow state contains duplicate proposals."
            )

        receipt_by_key = {
            (stored.proposal_id, stored.version): stored for stored in receipts
        }
        if len(receipt_by_key) != len(receipts):
            raise PersistenceCorruptionError(
                "Persistent calendar workflow state contains duplicate receipts."
            )

        terminal_statuses = {
            ProposalStatus.EXECUTED,
            ProposalStatus.FALLBACK_READY,
            ProposalStatus.EXECUTION_FAILED,
        }
        for proposal in proposals:
            key = (proposal.proposal_id, proposal.version)
            has_receipt = key in receipt_by_key
            if proposal.status in terminal_statuses and not has_receipt:
                raise PersistenceCorruptionError(
                    f"Completed calendar proposal lacks an execution receipt: "
                    f"{proposal.proposal_id}"
                )
            if proposal.status not in terminal_statuses and has_receipt:
                raise PersistenceCorruptionError(
                    f"Unfinished calendar proposal has a final execution receipt: "
                    f"{proposal.proposal_id}"
                )

        for stored in receipts:
            proposal = proposal_by_id.get(stored.proposal_id)
            if proposal is None or stored.version != proposal.version:
                raise PersistenceCorruptionError(
                    "Stored execution receipt does not match the current proposal "
                    f"version: {stored.proposal_id} version {stored.version}"
                )

        for record in audit_records:
            proposal = proposal_by_id.get(record.proposal_id)
            if proposal is None or record.version > proposal.version:
                raise PersistenceCorruptionError(
                    "Stored audit record references an unknown proposal version: "
                    f"{record.proposal_id} version {record.version}"
                )

        latest_audit: dict[str, AuditRecord] = {}
        for record in audit_records:
            latest_audit[record.proposal_id] = record
        for proposal in proposals:
            latest = latest_audit.get(proposal.proposal_id)
            if (
                latest is None
                or latest.version != proposal.version
                or latest.status is not proposal.status
            ):
                raise PersistenceCorruptionError(
                    "Stored calendar proposal lacks a matching final audit record: "
                    f"{proposal.proposal_id}"
                )
            if (
                proposal.status in terminal_statuses
                and latest.action is not AuditAction.EXECUTE
            ):
                raise PersistenceCorruptionError(
                    "Completed calendar proposal lacks a final execution audit: "
                    f"{proposal.proposal_id}"
                )
            if (
                proposal.status is ProposalStatus.EXECUTION_PENDING
                and latest.action is not AuditAction.APPROVE
            ):
                raise PersistenceCorruptionError(
                    "Interrupted calendar proposal lacks a durable approval audit: "
                    f"{proposal.proposal_id}"
                )

    def save_transition(
        self,
        proposal: CalendarProposal,
        audit_record: AuditRecord,
        *,
        expected: ProposalCheckpoint | None,
        receipt: ExecutionReceipt | None = None,
    ) -> None:
        proposal.validate()
        self._validate_audit(proposal, audit_record)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute(
                    "SELECT version, status FROM proposals WHERE proposal_id = ?",
                    (proposal.proposal_id,),
                ).fetchone()
                self._check_expected(proposal.proposal_id, current, expected)
                self._upsert_proposal(connection, proposal, audit_record.recorded_at)
                self._insert_audit(connection, audit_record)
                if receipt is not None:
                    self._upsert_receipt(
                        connection,
                        proposal.proposal_id,
                        proposal.version,
                        receipt,
                        audit_record.recorded_at,
                    )
                connection.commit()
        except PersistenceError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise PersistenceError(
                "Persistent calendar workflow state could not be updated; "
                "no completion should be reported."
            ) from exc

    def _initialize(self) -> None:
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect(initialize=False) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                    if not row[0].startswith("sqlite_")
                }
                if not tables:
                    connection.executescript(_SCHEMA)
                    connection.execute(
                        "INSERT INTO mc_metadata(key, value) VALUES (?, ?)",
                        ("schema_version", str(SCHEMA_VERSION)),
                    )
                    connection.commit()
                    return

                required = {
                    "mc_metadata",
                    "proposals",
                    "audit_records",
                    "execution_receipts",
                }
                if not required.issubset(tables):
                    raise PersistenceCompatibilityError(
                        "The selected database is not a compatible Mission Control "
                        "calendar state store."
                    )
                row = connection.execute(
                    "SELECT value FROM mc_metadata WHERE key = ?",
                    ("schema_version",),
                ).fetchone()
                if row is None or row[0] != str(SCHEMA_VERSION):
                    found = "missing" if row is None else row[0]
                    raise PersistenceCompatibilityError(
                        f"Unsupported calendar state schema version: {found}; "
                        f"expected {SCHEMA_VERSION}."
                    )
        except PersistenceError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise PersistenceCorruptionError(
                "Persistent calendar workflow state is unavailable or corrupt."
            ) from exc

    def _connect(self, *, initialize: bool = True) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        if initialize:
            row = connection.execute(
                "SELECT value FROM mc_metadata WHERE key = ?",
                ("schema_version",),
            ).fetchone()
            if row is None or row[0] != str(SCHEMA_VERSION):
                connection.close()
                raise PersistenceCompatibilityError(
                    "Calendar state schema changed or is incomplete."
                )
        return connection

    @staticmethod
    def _check_expected(
        proposal_id: str,
        current: sqlite3.Row | None,
        expected: ProposalCheckpoint | None,
    ) -> None:
        if expected is None:
            if current is not None:
                raise PersistenceConflictError(
                    f"Calendar proposal already exists: {proposal_id}"
                )
            return

        if current is None:
            raise PersistenceConflictError(
                f"Calendar proposal disappeared before update: {proposal_id}"
            )
        if (
            current["version"] != expected.version
            or current["status"] != expected.status.value
        ):
            raise PersistenceConflictError(
                f"Calendar proposal changed before update: {proposal_id}. "
                "Reload persistent state before deciding again."
            )

    @staticmethod
    def _validate_audit(
        proposal: CalendarProposal,
        audit_record: AuditRecord,
    ) -> None:
        if audit_record.proposal_id != proposal.proposal_id:
            raise ValueError("Audit proposal ID does not match transition")
        if audit_record.version != proposal.version:
            raise ValueError("Audit version does not match transition")
        if audit_record.status is not proposal.status:
            raise ValueError("Audit status does not match transition")
        if audit_record.recorded_at.tzinfo is None:
            raise ValueError("Audit timestamp must be timezone-aware")

    @staticmethod
    def _upsert_proposal(
        connection: sqlite3.Connection,
        proposal: CalendarProposal,
        recorded_at: datetime,
    ) -> None:
        values = (
            proposal.proposal_id,
            proposal.version,
            proposal.source.source_id,
            proposal.source.heading,
            proposal.source.context,
            proposal.rationale,
            proposal.event.title,
            proposal.event.start.isoformat(),
            _timezone_name(proposal.event.start),
            proposal.event.end.isoformat(),
            _timezone_name(proposal.event.end),
            proposal.event.description,
            proposal.event.location,
            proposal.event.uid,
            proposal.calendar_id,
            proposal.destination_label,
            json.dumps(proposal.assumptions),
            json.dumps(proposal.conflicts),
            proposal.status.value,
            recorded_at.isoformat(),
            recorded_at.isoformat(),
        )
        connection.execute(
            """
            INSERT INTO proposals(
                proposal_id, version, source_id, source_heading, source_context,
                rationale, event_title, start_at, start_timezone, end_at,
                end_timezone, event_description, event_location, event_uid,
                calendar_id, destination_label, assumptions_json,
                conflicts_json, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(proposal_id) DO UPDATE SET
                version = excluded.version,
                source_id = excluded.source_id,
                source_heading = excluded.source_heading,
                source_context = excluded.source_context,
                rationale = excluded.rationale,
                event_title = excluded.event_title,
                start_at = excluded.start_at,
                start_timezone = excluded.start_timezone,
                end_at = excluded.end_at,
                end_timezone = excluded.end_timezone,
                event_description = excluded.event_description,
                event_location = excluded.event_location,
                event_uid = excluded.event_uid,
                calendar_id = excluded.calendar_id,
                destination_label = excluded.destination_label,
                assumptions_json = excluded.assumptions_json,
                conflicts_json = excluded.conflicts_json,
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            values,
        )

    @staticmethod
    def _insert_audit(
        connection: sqlite3.Connection,
        record: AuditRecord,
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_records(
                proposal_id, version, action, status, detail, recorded_at,
                decision, execution_outcome, verified
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.proposal_id,
                record.version,
                record.action.value,
                record.status.value,
                record.detail,
                record.recorded_at.isoformat(),
                record.decision.value if record.decision is not None else None,
                (
                    record.execution_outcome.value
                    if record.execution_outcome is not None
                    else None
                ),
                _optional_bool_to_db(record.verified),
            ),
        )

    @staticmethod
    def _upsert_receipt(
        connection: sqlite3.Connection,
        proposal_id: str,
        version: int,
        receipt: ExecutionReceipt,
        recorded_at: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO execution_receipts(
                proposal_id, version, outcome, verified, message, provider,
                event_id, event_url, artifact_path, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(proposal_id, version) DO UPDATE SET
                outcome = excluded.outcome,
                verified = excluded.verified,
                message = excluded.message,
                provider = excluded.provider,
                event_id = excluded.event_id,
                event_url = excluded.event_url,
                artifact_path = excluded.artifact_path,
                recorded_at = excluded.recorded_at
            """,
            (
                proposal_id,
                version,
                receipt.outcome.value,
                int(receipt.verified),
                receipt.message,
                receipt.provider,
                receipt.event_id,
                receipt.event_url,
                str(receipt.artifact_path) if receipt.artifact_path else None,
                recorded_at.isoformat(),
            ),
        )

    @staticmethod
    def _proposal_from_row(row: sqlite3.Row) -> CalendarProposal:
        try:
            proposal = CalendarProposal(
                proposal_id=row["proposal_id"],
                version=int(row["version"]),
                source=SourceItem(
                    row["source_id"],
                    row["source_heading"],
                    row["source_context"],
                ),
                rationale=row["rationale"],
                event=MissionControlEvent(
                    title=row["event_title"],
                    start=_restore_datetime(row["start_at"], row["start_timezone"]),
                    end=_restore_datetime(row["end_at"], row["end_timezone"]),
                    description=row["event_description"],
                    location=row["event_location"],
                    uid=row["event_uid"],
                ),
                calendar_id=row["calendar_id"],
                destination_label=row["destination_label"],
                assumptions=_string_tuple(row["assumptions_json"]),
                conflicts=_string_tuple(row["conflicts_json"]),
                status=ProposalStatus(row["status"]),
            )
            proposal.validate()
            return proposal
        except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError) as exc:
            raise PersistenceCorruptionError(
                f"Stored calendar proposal is corrupt: {row['proposal_id']}"
            ) from exc

    @staticmethod
    def _audit_from_row(row: sqlite3.Row) -> AuditRecord:
        try:
            recorded_at = datetime.fromisoformat(row["recorded_at"])
            if recorded_at.tzinfo is None:
                raise ValueError("timezone-naive audit timestamp")
            return AuditRecord(
                proposal_id=row["proposal_id"],
                version=int(row["version"]),
                action=AuditAction(row["action"]),
                status=ProposalStatus(row["status"]),
                detail=row["detail"],
                recorded_at=recorded_at,
                decision=(
                    ProposalDecision(row["decision"])
                    if row["decision"] is not None
                    else None
                ),
                execution_outcome=(
                    ExecutionOutcome(row["execution_outcome"])
                    if row["execution_outcome"] is not None
                    else None
                ),
                verified=_optional_bool_from_db(row["verified"]),
            )
        except (TypeError, ValueError) as exc:
            raise PersistenceCorruptionError(
                f"Stored audit record is corrupt: {row['audit_id']}"
            ) from exc

    @staticmethod
    def _receipt_from_row(row: sqlite3.Row) -> StoredExecutionReceipt:
        try:
            return StoredExecutionReceipt(
                proposal_id=row["proposal_id"],
                version=int(row["version"]),
                receipt=ExecutionReceipt(
                    outcome=ExecutionOutcome(row["outcome"]),
                    verified=bool(row["verified"]),
                    message=row["message"],
                    provider=row["provider"],
                    event_id=row["event_id"],
                    event_url=row["event_url"],
                    artifact_path=(
                        Path(row["artifact_path"])
                        if row["artifact_path"] is not None
                        else None
                    ),
                ),
            )
        except (TypeError, ValueError) as exc:
            raise PersistenceCorruptionError(
                "Stored execution receipt is corrupt for "
                f"{row['proposal_id']} version {row['version']}"
            ) from exc


def _timezone_name(value: datetime) -> str | None:
    return getattr(value.tzinfo, "key", None)


def _restore_datetime(value: str, timezone_name: str | None) -> datetime:
    restored = datetime.fromisoformat(value)
    if restored.tzinfo is None:
        raise ValueError("stored event time is timezone-naive")
    if timezone_name:
        restored = restored.astimezone(ZoneInfo(timezone_name))
    return restored


def _string_tuple(payload: str) -> tuple[str, ...]:
    values = json.loads(payload)
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise ValueError("expected a JSON string list")
    return tuple(values)


def _optional_bool_to_db(value: bool | None) -> int | None:
    return None if value is None else int(value)


def _optional_bool_from_db(value: int | None) -> bool | None:
    if value is None:
        return None
    if value not in {0, 1}:
        raise ValueError("stored boolean is invalid")
    return bool(value)


_SCHEMA = """
CREATE TABLE mc_metadata(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE proposals(
    proposal_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL CHECK(version > 0),
    source_id TEXT NOT NULL,
    source_heading TEXT NOT NULL,
    source_context TEXT NOT NULL,
    rationale TEXT NOT NULL,
    event_title TEXT NOT NULL,
    start_at TEXT NOT NULL,
    start_timezone TEXT,
    end_at TEXT NOT NULL,
    end_timezone TEXT,
    event_description TEXT NOT NULL,
    event_location TEXT NOT NULL,
    event_uid TEXT,
    calendar_id TEXT NOT NULL,
    destination_label TEXT NOT NULL,
    assumptions_json TEXT NOT NULL,
    conflicts_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE audit_records(
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    decision TEXT,
    execution_outcome TEXT,
    verified INTEGER,
    FOREIGN KEY(proposal_id) REFERENCES proposals(proposal_id)
);

CREATE TABLE execution_receipts(
    proposal_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    verified INTEGER NOT NULL CHECK(verified IN (0, 1)),
    message TEXT NOT NULL,
    provider TEXT,
    event_id TEXT,
    event_url TEXT,
    artifact_path TEXT,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY(proposal_id, version),
    FOREIGN KEY(proposal_id) REFERENCES proposals(proposal_id)
);
"""
