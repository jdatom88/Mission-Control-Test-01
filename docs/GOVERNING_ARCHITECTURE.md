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

The binding service boundaries, approval semantics, briefing placement rules, execution paths, and progressive-automation constraints are specified in [Calendar Service Architecture](CALENDAR_SERVICE_ARCHITECTURE.md).

## Persistent calendar workflow state

Proposal, approval, audit, receipt, and recovery state must be owned by Mission Control behind a replaceable store boundary. Provider adapters and briefing presentation code must not own storage policy.

Approval must be durable before external execution begins. An approved operation whose final result is not durable must remain outside the active approval queue and must not be retried unless the executor explicitly supports duplicate-safe reconciliation. Store corruption, incompatibility, stale updates, and final-write failures must fail loudly.

The Stage 4 prototype uses SQLite as a commodity transactional implementation for the solo-operator slice. SQLite is not a constitutional dependency or a cloud synchronization strategy. The implementation decision and recovery rules are specified in [Stage 4 Persistence Decision](STAGE4_PERSISTENCE_DECISION.md).

For the approved pilot, one cloud Mission Control runtime owns the SQLite file on an encrypted persistent volume. All user devices access that state through the Mission Control API; they do not share the database file. A separately configured backup location, marked-volume identity checks, explicit one-time bootstrap, no-create normal startup, consistency-safe SQLite backups, clean-destination restoration, and semantic read-back form the pilot durability boundary. Missing or unexpected storage must stop the runtime rather than create an empty replacement. The complete host-neutral operating contract is specified in [Pilot Runtime Durability Contract](PILOT_RUNTIME_DURABILITY.md).

The application can enforce distinct configured roots and volume identities, but the deployment platform remains responsible for encryption, physical storage independence, backup scheduling, retention, and access control. Synthetic filesystem acceptance does not prove those provider properties. A real deployed-volume backup and restore rehearsal is required before operational reliance.

## Implementation sequencing

Build vertical slices that prove value end to end before broadening the system.

Vertical-slice sequence:

1. Calendar Service vertical slice — Tested
2. Connector state/health orchestration — Prototype
3. Direct Google Calendar path — Tested
4. One briefing path that consumes shared capabilities — Stage 3 Tested
5. Persistent proposal, approval, and audit state — Stage 4 Tested
6. Pilot runtime storage controls and synthetic backup/restore validation — feature-branch acceptance complete
7. Actual cloud runtime, encrypted-volume, scheduler, and clean-restore acceptance — NEXT
8. Additional connectors and domain packets only after the governed path is operationally durable

## Architecture conflict rule

Implementation sessions may fix defects and fill narrowly required technical gaps, but they must not invent or redefine Mission Control constitutional architecture. When implementation reveals a material architectural conflict, stop and surface the conflict to Mission Control Development for resolution.
