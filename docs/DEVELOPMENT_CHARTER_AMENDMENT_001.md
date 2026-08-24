# Mission Control Development Charter Amendment 001

## Status

Ratified by the Commander on August 24, 2026.

## Purpose

Clarify the authority and scope of the existing Railway and Cloudflare R2 pilot
deployment without expanding Mission Control into a multi-user or autonomous
platform.

## Decision

The Railway/R2 deployment is authorized as a narrow single-operator durability
exception to the Development Charter v1.1 preference against always-on
infrastructure during early development.

The exception authorizes:

- one Mission Control application/runtime writer;
- one operator-owned SQLite state boundary;
- one persistent Railway volume;
- one independent Cloudflare R2 recovery copy;
- storage health checks, verified backups, and clean restoration; and
- future multi-device access only through a separately authorized application
  API, never through shared database-file synchronization.

The exception does not authorize:

- multiple user accounts or tenants;
- concurrent application writers;
- autonomous orchestration;
- a general public product runtime;
- treating the storage guardian as a Mission Control application API; or
- Stable maturity without the remaining acceptance evidence.

## Present capacity boundary

The deployed system supports one operator's state and one runtime writer by
design. It currently supports zero product user accounts because no authenticated
application API, user model, onboarding flow, or user-facing interface exists.
Any future claim of support for multiple users requires a separate architecture,
security, data-isolation, and acceptance decision.

## Capital-conservation rule

Paid Railway snapshots, R2 retention/lock controls, volume-specific provider
evidence, and similar paid hardening are deferred until Pilot RC1 or an
equivalent working prototype of the whole OS is ready for real-use evaluation.
No subscription or paid infrastructure upgrade occurs without explicit operator
approval. Issue #9 remains open and Pilot Runtime SQLite Durability remains
Prototype until the deferred gates are completed or formally replaced.

## Next product milestone

The next authorized milestone is the Knowledge Layer Foundation: an Executive
Status Packet schema and validator, explicit user/domain data boundaries, and a
small evidence/provenance contract usable by future Calendar, Gmail, briefing,
RIE, and MCOM capabilities.
