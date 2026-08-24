# Mission Control OS — Governing Architecture

## Purpose

Mission Control OS is a governed personal executive operating system designed to reduce friction between knowing, deciding, and doing.

This document summarizes the implementation-relevant architecture already established in Mission Control Development. It is not a replacement for the full constitutional charters; it is the engineering handoff required to keep implementation aligned.

## Core design laws

### Human Agency First
Mission Control may observe, recommend, and prepare before execution. Execution requires appropriate user authorization unless a class of action has been explicitly delegated.

### Progressive Automation
Observe → Recommend → Prepare → Approve → Execute → Learn.

### Reliability
Fail loudly. Never fake completion. Never present an artifact, connector action, or external write as completed unless it is verified.

### Friction Reduction
Every capability should reduce cognitive, operational, or administrative friction. Prefer eliminating a step over automating it, automating over simplifying, simplifying over guiding, and guiding over merely informing.

### Commodity Capability Reuse
Before building a capability, search for a mature, lightweight, maintained library, skill, connector, package, or open standard that solves the commodity portion of the problem. Mission Control should build only the intelligence and integration layer that makes the capability uniquely useful.

### Solo-Operator Constraint
Prefer small scripts, simple files, replaceable components, and infrastructure that a single part-time maintainer can understand and recover after time away.

The deployed Railway/R2 durability boundary is a narrow single-operator exception recorded in [Development Charter Amendment 001](DEVELOPMENT_CHARTER_AMENDMENT_001.md). It authorizes one runtime writer and one operator-owned state boundary, not multi-user functionality, autonomous orchestration, or a general application platform.

## Generation 1 product boundary

Generation 1 is a single-operator Mission Control product delivered through a private, mobile-responsive web application.

The private web application is the canonical Generation 1 delivery surface. A native or installable application may be developed later, but it must reuse the same backend contracts, security boundaries, Knowledge Layer, and connector boundaries rather than creating a parallel product architecture.

Generation 1 does not authorize:

- multi-user tenancy or shared user accounts
- Gmail mutation
- autonomous external actions outside existing approval rules
- credentials or refresh tokens stored in GitHub
- removal or weakening of existing approval requirements

## Four implementation layers

1. **Knowledge Layer** — charters, packets, configuration, user/domain state.
2. **Retrieval Layer** — connectors and adapters that pull or normalize external data.
3. **Reasoning Layer** — synthesis, scoring, prioritization, recommendation logic.
4. **Output Layer** — briefings, reports, files, actions, and user-facing artifacts.

Do not prematurely split decision, execution, or learning into independent services unless real complexity requires it.

## Shared capability rule

Subsystems should consume centralized capabilities rather than independently reimplementing commodity behavior.

Current example:

Mission Control subsystem → canonical event object → Calendar Service → direct calendar connector when available OR `icalendar` ICS adapter as universal fallback → validation → verified result.

## Connector state model

Mission Control must distinguish at least:

- connected + authorized + data found
- connected + authorized + no matching data
- connected + insufficient scope
- connected + wrong account
- authentication expired
- runtime capability unavailable while the connector may remain healthy
- provider rate limited
- connector unavailable
- execution failure
- unknown

Do not collapse these conditions into a generic “not connected” message.

## Calendar architecture

All Mission Control calendar-producing subsystems must route through the centralized Calendar Service.

The briefing/reasoning layer must not construct raw ICS text.

Calendar recommendations must first appear inline with the correspondence or intelligence that gives them meaning, then reappear in an approval queue with their source context and value rationale intact. The user may Approve, Edit, Reject, or Defer. An edited proposal requires renewed approval before execution.

For the three-part Expanded Intelligence Brief, each part ends with a queue for proposals introduced in that part. Unresolved proposals carry forward into the final Part Three queue. This reinforcement loop must preserve the value of the recommendation without interrupting canonical reading or audio narration.

Preferred execution path:

Mission Control event → validate → authorized calendar connector → verify creation.

For Google Calendar, verification requires a separate provider read after creation. The create response alone is not sufficient. Mission Control must preserve an operation identifier and the connector must derive a valid deterministic Google event ID so an uncertain retry can read the known event rather than create a duplicate.

Fallback path:

Mission Control event → validate → ICS adapter → `icalendar` → parse-back validation → semantic/artifact checks → verified `.ics` file.

The phrase “Download ICS” must never be displayed unless a real verified artifact exists.

Emailing a verified ICS artifact is an authorized fallback delivery path, not proof of calendar creation. Delivery, client import, and direct provider creation are separate outcomes and must be reported separately.

Every briefing calendar read must use a fresh explicit time window through the
provider-neutral read boundary. A healthy empty result is not a connector
failure. A runtime that cannot invoke the calendar capability must report the
runtime limitation without labeling Google Calendar unavailable. Read-only
transient failures may retry no more than three times, and a later fresh live
success supersedes stale historical failure state.

The binding service boundaries, approval semantics, briefing placement rules, execution paths, and progressive-automation constraints are specified in [Calendar Service Architecture](CALENDAR_SERVICE_ARCHITECTURE.md).

## Persistent calendar workflow state

Proposal, approval, audit, receipt, and recovery state must be owned by Mission Control behind a replaceable store boundary. Provider adapters and briefing presentation code must not own storage policy.

Approval must be durable before external execution begins. An approved operation whose final result is not durable must remain outside the active approval queue and must not be retried unless the executor explicitly supports duplicate-safe reconciliation. Store corruption, incompatibility, stale updates, and final-write failures must fail loudly.

The Stage 4 prototype uses SQLite as a commodity transactional implementation for the solo-operator slice. SQLite is not a constitutional dependency or a cloud synchronization strategy. The implementation decision and recovery rules are specified in [Stage 4 Persistence Decision](STAGE4_PERSISTENCE_DECISION.md).

For the approved pilot, one cloud Mission Control runtime owns the SQLite file on an encrypted persistent volume. All user devices access that state through the Mission Control API; they do not share the database file. A separately configured backup location, marked-volume identity checks, explicit one-time bootstrap, no-create normal startup, consistency-safe SQLite backups, clean-destination restoration, and semantic read-back form the pilot durability boundary. Missing or unexpected storage must stop the runtime rather than create an empty replacement. The complete host-neutral operating contract is specified in [Pilot Runtime Durability Contract](PILOT_RUNTIME_DURABILITY.md).

The application can enforce distinct configured roots and volume identities, but the deployment platform remains responsible for encryption, physical storage independence, backup scheduling, retention, and access control. Synthetic filesystem acceptance does not prove those provider properties. A real deployed-volume backup and restore rehearsal is required before operational reliance.

For the pilot deployment, Railway is the selected single-instance application
host and Cloudflare R2 is the selected provider-independent object backup. The
integration remains thin and S3-compatible rather than making R2 constitutional
architecture. Railway's same-provider volume snapshots are defense in depth,
not the independent recovery copy. This selection does not authorize multiple
writers, a full briefing API, or maturity promotion without deployed read-back
and clean-restore evidence.

## Generation 1 security boundary

After Knowledge Layer Foundation acceptance, the next authorized platform milestone is a single-operator Railway security boundary.

That boundary must provide:

- private operator authentication for the Mission Control web application
- server-side Google OAuth rather than browser-held provider credentials
- encrypted persistent storage for Google refresh tokens outside GitHub
- explicit separation among application code, operator knowledge, credentials/secrets, and runtime/audit state
- restart validation proving authorized credentials can be reloaded and used after process restart without re-authentication by accident or silent credential loss
- read-back validation that proves the persisted credential belongs to the expected operator/provider context before it is trusted

The security boundary is for one operator only. It is not a tenancy model and must not create generalized user-account infrastructure beyond what the private Generation 1 operator surface requires.

## Generation 1 web application boundary

After the single-operator security boundary is accepted, Mission Control may build the private mobile-responsive web application.

The application must:

- use the accepted Knowledge Layer contract rather than inventing a second data model
- reuse the existing single-runtime persistence and connector architecture
- present Mission Control outputs and governed actions through a mobile-first responsive interface
- preserve existing approval requirements for external writes
- access operator state through the Mission Control backend rather than exposing SQLite or provider tokens directly to clients

A native or installable application remains a later delivery option using the same backend boundaries.

## Knowledge Layer packet boundary

The first Generation 1 Knowledge Layer record is the versioned Executive Status
Packet. JSON is the canonical interchange format. Mission Control owns the
packet semantics while Pydantic 2 supplies replaceable validation and JSON
Schema mechanics.

Version `1.0` requires domain/project identity, lifecycle status, an
offset-aware update time, current focus, progress, risks, opportunities, active
tasks, pending decisions, next milestone, overall confidence, and provenance.
Provenance distinguishes facts, assumptions, inferences, predictions, and
recommendations while preserving source identity/reference, observation time,
confidence, and rationale.

Unknown fields and unsupported versions fail loudly; no future data is silently
discarded. Real operator packets live outside the product repository. Runtime
state uses a separate, non-nested external root. Credentials come only from a
sealed environment or encrypted runtime credential store. The complete contract
is specified in [Knowledge Layer Foundation](KNOWLEDGE_LAYER_FOUNDATION.md).

## Implementation sequencing

Build vertical slices that prove value end to end before broadening the system.

Completed/closed sequence:

1. Calendar Service vertical slice — Tested
2. Connector state/health orchestration — Tested
3. Direct Google Calendar path — Tested
4. One briefing path that consumes shared capabilities — Stage 3 Tested
5. Persistent proposal, approval, and audit state — Stage 4 Tested
6. Pilot runtime storage controls and synthetic backup/restore validation — feature-branch acceptance complete
7. Actual cloud runtime and independent clean-restore acceptance — core deployed acceptance complete; paid snapshot/retention evidence remains deferred at Prototype
8. Governed Google Calendar read path for briefings — Tested
9. Calendar-closure review before Email Intelligence or other domain expansion — complete; narrow assembly milestone approved
10. Calendar Runtime Assembly — Tested
11. Current calendar implementation track — closed at Tested; Stable hardening remains explicit follow-on work
12. Governance and canonical-state reconciliation — complete

Canonical Generation 1 implementation sequence:

13. **Knowledge Layer Foundation** — Tested; the Executive Status Packet schema, validator, data boundary, and evidence/provenance contract passed Issue #21 acceptance.
14. **Single-Operator Railway Security Boundary** — current activated milestone; on explicit implementation instruction, implement private operator authentication, server-side Google OAuth, encrypted persistent refresh-token storage, restart validation, and credential read-back validation.
15. **Private Mobile-Responsive Mission Control Web Application** — build the Generation 1 delivery surface using the accepted Knowledge Layer contract and existing single-runtime architecture.
16. **Read-Only Gmail Intelligence Vertical Slice** — begin as a separately governed capability only after the preceding Generation 1 foundation and delivery-surface milestones are established.

This ordering supersedes the earlier sequence that placed Gmail Intelligence immediately after Knowledge Layer acceptance.

Paid Railway snapshots, provider retention controls, and other deferred Stage 5 hardening remain outside the critical path until Pilot RC1 or an equivalent whole-OS working prototype justifies the cost and receives explicit operator approval.

## Architecture conflict rule

Implementation sessions may fix defects and fill narrowly required technical gaps, but they must not invent or redefine Mission Control constitutional architecture. When implementation reveals a material architectural conflict, stop and surface the conflict to Mission Control Development for resolution.
