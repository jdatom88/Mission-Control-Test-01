# Changelog

## 2026-08-16 — Direct Google Calendar connector prototype

Added provider-neutral direct-calendar orchestration and a thin Google Calendar API v3 adapter. The governed path now checks calendar write access, creates with `events.insert`, performs an independent `events.get` read-back, compares canonical event semantics, and reports verification failure separately from execution failure.

Added duplicate-safe retry behavior using a caller-preserved Mission Control operation ID and a deterministic Google-safe event ID. A Google `409` response triggers read-back of that known ID rather than a blind second mutation. Added connector-state handling for wrong account, insufficient scope, expired authorization, temporary provider unavailability, missing read-back data, execution failure, and semantic verification failure.

The full regression suite passes **16 tests**, and a live acceptance run confirmed owner access to the connected primary Google Calendar. The authorized test event was created and independently read back with matching provider ID, title, description, attendees, visibility, transparency, conferencing state, and equivalent start/end instants. The event was then deleted, and a bounded active-calendar search confirmed it was absent.

Direct Google Calendar Write remains **Prototype**, not Tested. The available connector read-back normalized the timestamps to an equivalent numeric offset but did not expose Google's stored `start.timeZone` and `end.timeZone` IANA fields. Exact `America/Los_Angeles` persistence therefore remains unverified and is tracked in GitHub Issue #2. This is a truthful partial acceptance, not completion.

## 2026-08-16 — Calendar proposal reinforcement architecture

Ratified and documented the governed Calendar Service workflow for briefing-generated proposals. A proposal now has two required presentation points: inline with the correspondence or intelligence that establishes its value, and again in an approval queue with enough context to support an informed Approve, Edit, Reject, or Defer decision. Each part of the Expanded Intelligence Brief receives its own queue, and unresolved proposals carry forward into the final Part Three queue.

Documented the Calendar Service ownership boundary, renewed approval after edits, direct-connector and verified-ICS paths, authorized email delivery as a fallback distinct from calendar import, fail-loud verification, retry/idempotency expectations, auditability, and progressive delegation constraints.

The architecture clarification itself did not change runtime maturity. Later in the same validation cycle, the required real-client acceptance evidence was received as recorded below. GitHub Issue #1 was closed with that acceptance evidence on 2026-08-16.

Runtime-validation result: the Calendar Service regression suite passed all 3 tests, and a generated `America/Los_Angeles` Stage 1 ICS artifact passed internal validation, was delivered by email, and was successfully imported into Apple Calendar. The Calendar Event Schema / Service and ICS Export are promoted from **Prototype** to **Tested**. They are not yet **Stable**; direct-connector and routine-use validation remain future work.

## 2026-08-15 — Stage 1 scaffold

Initialized the canonical Mission Control OS pilot repository. Added the Calendar Service prototype backed by the maintained `icalendar` library, initial regression tests, the connector state model, implementation-state handoff, governing architecture summary, and capability registry.

The current system is intentionally narrow. The Calendar Service remains Prototype until its automated tests are executed and a generated `.ics` file passes a real calendar-client import test. Broader briefing, Gmail, RIE, MCOM, and other subsystem implementation should not begin until this vertical slice is validated.
