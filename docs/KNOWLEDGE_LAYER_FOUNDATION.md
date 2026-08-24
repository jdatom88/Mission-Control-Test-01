# Knowledge Layer Foundation

## Decision

Mission Control uses one canonical **Executive Status Packet** encoded as JSON
and validated by the Pydantic 2 model in
`mission_control/knowledge/status_packet.py`. The initial schema version is
`1.0`, and the packet kind is `mission_control.executive_status`.

This is a Mission Control-owned semantic contract over a maintained commodity
validation library. Pydantic is replaceable; packet meaning and compatibility
rules belong to Mission Control.

## Required packet content

A packet requires domain/project identity, lifecycle status, an offset-aware
`last_updated` timestamp, current focus, recent progress, risks, opportunities,
active tasks, pending decisions, next milestone, overall confidence, and the
provenance records referenced by its contents. Project identity is optional so
a packet can represent a whole domain; all collection fields are required and
may be empty.

Allowed lifecycle states are `planned`, `active`, `at_risk`, `blocked`,
`paused`, `complete`, and `archived`. Confidence is a number from `0.0` through
`1.0`. Dates and times must be ISO 8601 timestamps with explicit offsets.

## Evidence and provenance

Each provenance record preserves:

- a unique record ID;
- source identity and an optional source reference;
- the observation or retrieval time;
- classification as `fact`, `assumption`, `inference`, `prediction`, or
  `recommendation`;
- confidence from `0.0` through `1.0`; and
- rationale explaining why the record supports the packet.

Progress, risk, opportunity, task, and decision records may reference one or
more provenance IDs. Unknown and duplicate provenance IDs fail validation.

## Compatibility and failure behavior

Version `1.0` is strict. Missing required fields, unexpected fields, invalid
types, invalid enumerations, naive timestamps, out-of-range confidence,
unsupported versions, foreign packet kinds, foreign domains, and broken
provenance references fail loudly with field-specific messages. Nothing is
silently discarded. A future schema requires an explicit version and migration
decision rather than permissive loading.

## Data ownership boundary

| Data class | Owner and location | Repository rule |
|---|---|---|
| Product code, schema, synthetic fixtures, non-user defaults | Canonical GitHub repository | Allowed |
| Operator-owned knowledge packets | Configured private runtime knowledge root | Never commit real operator data |
| Credentials and OAuth secrets | Railway sealed environment or later encrypted runtime credential store | Never commit or log |
| Runtime state and audit records | Configured private runtime state root | Never place inside the repository |

Operator knowledge and runtime state must use distinct, non-nested roots outside
the repository. The enforceable path and credential-source rules live in
`mission_control/knowledge/boundary.py`.

## Scope boundary

This milestone defines and validates knowledge. It does not implement Railway
operator authentication, Google OAuth/token persistence, the Generation 1 web
application, Gmail retrieval or mutation, a full Briefing Engine, or autonomous
execution.
