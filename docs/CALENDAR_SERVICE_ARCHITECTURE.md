# Mission Control OS — Calendar Service Architecture

## Status and purpose

This document defines the governed Calendar Service boundary and the ratified calendar-proposal workflow for Mission Control OS. It describes the target architecture; it does not assert that every path is implemented or runtime-validated.

The Calendar Service is the only Mission Control component authorized to create, update, delete, export, or verify calendar events. Briefings and domain modules may identify commitments and recommend events, but they must submit canonical event proposals to the Calendar Service rather than write calendars or construct ICS content themselves.

## Ownership boundaries

- **Briefing and reasoning layers** identify a time-bound commitment, explain why it matters, and prepare a calendar proposal.
- **Mission Control UI/runtime** presents the proposal, preserves its relationship to the underlying correspondence or intelligence, and collects the user's decision.
- **Calendar Service** validates the canonical event, checks connector readiness, executes only an authorized action, verifies the result, and returns a truthful outcome.
- **Scheduling and Automation** owns recurring or conditional rules after the user has explicitly delegated them. It still routes calendar mutations through the Calendar Service.
- **Calendar connectors and the ICS adapter** are thin, replaceable integrations. They must not contain Mission Control reasoning or approval policy.

## Canonical proposal lifecycle

The default lifecycle is:

1. Identify a potential commitment or scheduling opportunity from authoritative source material.
2. Prepare a canonical event proposal with its source reference, recommendation rationale, timing, timezone, duration, participants when applicable, and any detected conflicts or assumptions.
3. Present the proposal inline with the relevant correspondence or intelligence.
4. Add the same proposal to the briefing's pending calendar queue.
5. Reintroduce the proposal at the applicable end-of-section or end-of-brief approval queue, including enough source context and value rationale for the user to evaluate it without relying on memory.
6. Ask the user to **Approve**, **Edit**, **Reject**, or **Defer**.
7. If edited, present the revised proposal for approval. An edit is not authorization to execute.
8. If approved, validate and execute through the selected calendar path.
9. Verify the external write or the fallback artifact before reporting success.
10. Record the decision, execution result, and any partial failure or recovery action in the audit history.

No calendar event is created merely because it was recommended or displayed in a briefing.

## Briefing placement and reinforcement loop

Calendar proposals use two deliberate presentation points:

### Inline presentation

The first presentation appears beside the correspondence, deadline, intelligence, or recommendation that created the scheduling need. It must state:

- the proposed event and timing;
- why the event is valuable or necessary;
- the source or triggering item;
- material assumptions, conflicts, or timing constraints; and
- that the item is a proposal awaiting a decision.

Inline presentation establishes context but does not interrupt the canonical briefing narration to force an immediate decision.

### Approval queue

The proposal is presented again in an approval queue after the user has received the relevant briefing context. The queue must preserve the proposal's value, not merely repeat its title and date. Each item offers **Approve**, **Edit**, **Reject**, and **Defer**.

For a standard briefing, unresolved calendar proposals appear in the end-of-brief queue.

For the three-part Expanded Intelligence Brief:

- each part ends with a queue containing the proposals introduced in that part;
- a deferred or otherwise unresolved proposal remains pending; and
- every unresolved proposal is carried forward and reintroduced in the final Part Three queue with its source context and value rationale intact.

This reinforcement loop is required so the user does not lose either the recommendation or the reason it was made as the briefing progresses.

Reading or audio mode must remain coherent. Proposal markers may be narrated in context, but approval interaction occurs in the queue rather than breaking the canonical narration.

## Decision semantics

- **Approve** authorizes the specific displayed event and the selected destination calendar for one execution attempt and its governed retries.
- **Edit** changes proposal fields but does not authorize execution. The revised event must be shown again for approval.
- **Reject** closes the proposal without a calendar write and records the decision.
- **Defer** leaves the proposal unresolved and eligible for the applicable carry-forward queue. Deferral must never be reported as rejection or approval.

Approval applies to the specific proposal version shown to the user. A material change to time, recurrence, attendees, destination, or purpose creates a revised version that requires renewed approval unless that exact class of change has been explicitly delegated.

## Execution paths

### Preferred direct connector path

Canonical event → schema validation → connector state check → conflict/availability check when supported → authorized create/update/delete → provider read-back or receipt verification → truthful result.

Google Calendar is the first direct connector prototype. Additional providers remain replaceable adapters behind the same Calendar Service contract.

The Google Calendar adapter accepts an externally authorized API v3 client and must not store OAuth credentials in the repository. Its create path is:

1. Confirm write access to the selected calendar.
2. Derive a Google-safe event ID from the Mission Control operation ID.
3. Call `events.insert` once.
4. Call `events.get` independently using the returned provider event ID.
5. Compare title, start, end, timezone, description, location, status, and provider identity with the approved canonical event.
6. Report success only when the read-back matches.

Equivalent instants alone do not satisfy timezone verification when the approved event names an IANA timezone. Prefer a read-back surface that exposes and compares the provider's stored `start.timeZone` and `end.timeZone` values. When the available surface omits those raw fields, Tested maturity may instead use the combination of equivalent-instant read-back, an active-calendar search rendered in the requested IANA timezone, and explicit user confirmation that the event is visible at the requested local time. Raw IANA-field retrieval remains required hardening evidence before Stable maturity.

If Google reports that the deterministic event ID already exists, the connector reads that event instead of blindly repeating the create request. The caller must preserve the Mission Control operation ID with the approval/audit record so retry remains duplicate-safe.

### Governed briefing read path

Every briefing run performs a new bounded calendar read for an explicit
timezone-aware start and end. The provider adapter maps timed and all-day events
into the canonical read model and returns either healthy data or a healthy empty
window. Historical status text is never used as the current result.

The Google read adapter uses `events.list` with the selected calendar ID,
RFC3339 bounds, recurring-event expansion, start-time ordering, deleted-event
exclusion, a bounded result limit, and an optional IANA response timezone. HTTP
401, 403, 404, 429, and 5xx outcomes remain distinct. Read-only rate-limit and
provider-unavailable responses may be attempted up to three times; auth, scope,
account, malformed-response, and runtime-capability failures are not retried.

If the current execution runtime cannot invoke Calendar, the briefing reports
the runtime limitation for that run. It must not call Google Calendar
unavailable when the connector has not failed. A later fresh successful read
supersedes the earlier runtime failure.

### Universal ICS fallback

Canonical event → schema validation → ICS adapter → maintained `icalendar` library → parse-back validation → semantic and artifact checks → verified `.ics` file.

The UI may offer download or delivery only after a real artifact passes validation. An ICS file is a portable proposal artifact, not proof that an event was added to a calendar.

When the user authorizes delivery, a verified ICS artifact may be attached to an email sent to the user's verified destination. Email delivery must report message delivery separately from calendar import; sending the attachment does not prove that Apple Calendar, Google Calendar, or another client imported it.

## Reliability, retries, and recovery

- Fail loudly and distinguish connector state, validation failure, execution failure, verification failure, and artifact-delivery failure.
- Never show success without provider verification or a verified fallback artifact, as applicable.
- Preserve the canonical event and approval record so a failed execution can be retried without reconstructing the proposal.
- Use idempotency or provider identifiers to prevent duplicate events during retry.
- Default connector retrieval behavior may attempt up to three times before requesting approval for troubleshooting; calendar mutation retries must remain bounded and duplicate-safe.
- Report partial outcomes precisely. For example: “ICS email delivered; calendar import not verified” is not “event created.”
- Updates and deletion require the same governed authorization boundary unless explicitly delegated.
- Preserve sufficient audit history to support undo or compensating action when the provider permits it.

## Progressive automation

Calendar automation advances through the Mission Control sequence:

Observe → Recommend → Prepare → Approve → Execute → Learn.

Repeated user approval may inform better proposals, but it does not silently create standing authority. Automatic creation is permitted only after the user explicitly delegates a narrowly defined rule, destination, and action scope. Delegated actions must remain auditable, revocable, observable in the briefing, and subject to fail-loud verification.

## Stage 1 validation boundary

Stage 1 validates the canonical event-to-verified-ICS vertical slice in automated tests and a real calendar-client import. Direct calendar creation, briefing queue UI, email delivery automation, recurrence operations, and delegated rules are later implementation slices unless the implementation state explicitly promotes them.

Architecture documentation must not be treated as runtime completion. Capability maturity changes only when the acceptance evidence named in the Capability Registry is satisfied.
