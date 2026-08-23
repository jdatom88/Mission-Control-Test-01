# Changelog

## 2026-08-23 — Stage 5 provisioning opened

Reverified draft PR #11 at head
`843bc2b518330ba5fb2fc6e5f5a82327c249c442` with canonical GitHub Actions run
#14 successful, marked it ready for review, and squash-merged the Railway/R2
deployment integration into canonical `main` as
`f7b8693968467c88506db774d2e5af0b082b22e7`.

The operator reported Railway and Cloudflare account setup complete. The first
live provisioning attempt reached Railway's GitHub sign-in boundary and a
Cloudflare human-verification challenge, so automation stopped before any
credential entry or provider mutation. No Railway service or volume, R2 bucket
or token, retention control, billing action, or deployed runtime was created or
verified. No secret was transmitted or persisted, and live calendar mutations
remain **0**.

Pilot Runtime SQLite Durability remains **Prototype**. GitHub Issue #9 remains
open. NEXT is direct provider authentication followed by the documented private
R2 bucket/token, single Railway service and `/data` volume, bootstrap,
read-back-verified backup, fail-loud check, and quarantine-first restore gates.

## 2026-08-20 — Railway/R2 deployment integration prototype

Merged the host-neutral pilot durability controls from PR #10 into canonical
`main` at `ff72cdfb94285dd7e77a9396f71c170b3b1921ab`. GitHub Issue #9 remains open
for the real infrastructure gate.

Selected Railway as the single-instance pilot application host and Cloudflare
R2 as the provider-independent backup target. Added a thin S3-compatible
adapter that reinspects the consistency-safe local SQLite backup, uploads it,
downloads the complete object again, verifies SHA-256 metadata and bytes,
revalidates SQLite and Mission Control workflow semantics, and issues a receipt
only after read-back succeeds. Added safe offsite fetch into local staging with
configured-prefix restriction and no overwrite.

Added a fail-loud storage guardian with a Railway health endpoint, periodic
marked-volume and semantic checks, and a minimum-daily verified offsite backup
loop. Added a Dockerfile, Railway config-as-code, and a deployment runbook that
keeps the one-volume local staging copy distinct from the independent R2
recovery copy and preserves the one-writer boundary.

Added **10 focused offsite and guardian tests**. The complete repository suite
now passes **65 tests**. The Stage 4 and Stage 5 separate-process acceptance
harnesses remain green, dependency checks pass, and live calendar mutations
remain **0**. Canonical GitHub Actions run #13 passed the 65-test suite and both
acceptance harnesses on draft PR #11.

Pilot Runtime SQLite Durability remains **Prototype**. No Railway or Cloudflare
account, paid service, volume, bucket, credential, lifecycle rule, or deployed
restore has been created or validated. Railway volume-specific encryption
applicability must be captured during provisioning; it is not inferred from a
generic security control.

## 2026-08-20 — Pilot runtime durability controls prototype

Ratified the single-runtime pilot decision: one cloud Mission Control application instance owns the SQLite calendar-state file on an encrypted persistent volume, while all user devices access it through the application API. Managed shared storage remains deferred behind explicit migration triggers rather than being introduced before multiple writers, users, services, or tighter recovery requirements exist.

Added an explicit marked-volume runtime boundary. Four required environment values identify separate state and backup roots. One-time bootstrap creates role/identity markers and the initial database; normal startup refuses to initialize missing state. Missing or mismatched markers, absent databases, symbolic links, unexpected file types, read-only paths, unavailable SQLite write locks, schema incompatibility, corruption, foreign-key failures, and semantic incompleteness now fail loudly.

Added consistency-safe backup and restore operations using Python SQLite's online backup API. Backup validates SQLite integrity and Mission Control semantics, refuses unsafe names and overwrite, publishes the validated file without overwrite, and reports a SHA-256 digest and record counts. Restore accepts only a configured backup, refuses an existing live destination, validates a partial restoration, publishes without overwrite, reopens through normal runtime checks, and compares the final workflow snapshot with the source backup.

Added an operational CLI plus the Pilot Runtime Durability Contract covering configuration, one-time bootstrap, startup health checks, backup cadence, retention, quarantine-first recovery, clean restore, fail-loud behavior, and managed-database migration triggers.

Added **14 focused durability tests**. The complete repository suite now passes **55 tests**. A new separate-process acceptance bootstrapped marked roots, persisted deferred and synthetically completed proposals, created a verified online backup, deliberately removed the live database inside a temporary directory, confirmed startup failed without creating an empty replacement, restored into the clean destination, and independently verified proposals, value context, queue state, audit history, and execution receipt. It reported `STAGE5_SEPARATE_PROCESS_DURABILITY_ACCEPTANCE=PASS`, `BACKUP_RESTORE_SEMANTICS=VERIFIED`, `MISSING_STORE_FAIL_LOUD=VERIFIED`, and `LIVE_CALENDAR_MUTATIONS=0`. The Stage 4 five-process harness also remains green.

Canonical GitHub Actions run #10 passed the dependency check, all 55 tests, the Stage 4 persistence acceptance, and the new pilot durability acceptance.

Pilot Runtime SQLite Durability is registered as **Prototype**, not Tested. The evidence validates the host-neutral software boundary only. An actual cloud runtime, encrypted persistent state volume, independently durable backup location, external scheduler/retention policy, and deployed clean-restore rehearsal have not yet been selected or validated.

## 2026-08-17 — Persistent briefing-calendar state promoted to Tested

Reran the complete Stage 4 acceptance after publication. All **15 focused persistence tests** and all **41 repository tests** passed. The five-process harness again completed prepare/defer, restore/edit, approval-before-execution, synthetic interruption, restart, duplicate-safe recovery, and final receipt verification. Its assertion gate again reported `STAGE4_SEPARATE_PROCESS_ACCEPTANCE=PASS` and `LIVE_CALENDAR_MUTATIONS=0`.

Canonical GitHub CI passed for both the implementation and maturity-update heads. Briefing Calendar Persistent State is promoted from **Prototype** to **Tested** on the combined regression, separate-process runtime, interruption/recovery, rerun, and canonical CI evidence.

This promotion does not make the capability **Stable** and does not claim multi-device cloud synchronization. The pilot runtime still needs an explicit durable-volume location plus backup/restore policy and validation before operational reliance on the SQLite file.

## 2026-08-16 — Persistent briefing-calendar state prototype

Added the Stage 4 `CalendarProposalStore` boundary and a thin SQLite implementation using Python's maintained standard library. The storage decision compares structured files, SQLite, and hosted relational storage; SQLite is selected only for the local single-operator prototype and remains replaceable behind the Mission Control-owned protocol.

Proposal state, source context, rationale, event data, IANA timezone names, version, decision status, audit records, verified execution receipts, and ICS artifact references now survive workflow restarts. Schema-version, corruption, incomplete-state, and foreign-database checks fail loudly rather than silently returning an empty queue. OAuth credentials and provider tokens are not stored.

Approval is now durably transitioned to `execution_pending` before any external write. That state is excluded from the active approval queue and cannot be approved twice. If execution is interrupted or final receipt persistence fails, restart exposes the operation for explicit recovery. Recovery is attempted only through an executor that advertises duplicate-safe reconciliation; otherwise no retry occurs. Optimistic version/status checks prevent stale workflow instances from overriding a later decision or initiating an external write.

Added **15 focused persistence tests** covering restart, deferred carry-forward, edited-version restoration, terminal decisions, approval-before-execution ordering, interrupted execution, duplicate-safe recovery, stale-state conflicts, persistence failures before and after external execution, receipt restoration, and corrupt/incompatible/incomplete state. The full suite passes **41 tests**.

Added a reproducible five-process runtime harness. It prepared and deferred a proposal, restored and edited it, persisted approval before a synthetic external side effect, simulated process interruption, restored the quarantined operation, reconciled it through the recovery contract, and verified the final receipt in another process. The assertion gate reported `STAGE4_SEPARATE_PROCESS_ACCEPTANCE=PASS` and `LIVE_CALENDAR_MUTATIONS=0`.

Briefing Calendar Persistent State remains **Prototype**, not Tested, until the feature branch receives canonical review and CI. Pilot durable-volume and backup/restore policy also remain operational prerequisites before relying on the local SQLite file.

## 2026-08-16 — Governed briefing-to-calendar workflow promoted to Tested

Added the narrow Stage 3 briefing-to-calendar vertical slice using synthetic source material and in-memory state. A versioned calendar proposal preserves its source reference, source context, value rationale, destination, assumptions, conflicts, canonical event, and duplicate-safe operation ID.

Added separate inline and reinforced approval-queue renderings. The workflow supports Approve, Edit, Reject, and Defer; a revised proposal becomes a new pending version and cannot execute without renewed approval. Rejected proposals leave the queue, while deferred proposals carry forward into the final queue.

Approved proposals execute only through a Calendar Service executor. Direct execution uses the existing provider read-back path. When direct creation is not verified, the fallback may generate and validate an ICS artifact while reporting that manual import is still required. It never reports an ICS file as a calendar import or direct provider creation.

Added explicit audit records for proposal version, decision, status, execution outcome, verification flag, detail, and timestamp. The full regression suite passes **26 tests**. Synthetic runtime acceptance exercised Approve, Edit with renewed approval, Reject, Defer carry-forward, fail-loud verification failure, and verified ICS fallback without a live mutation.

The authorized live acceptance then created `Mission Control Stage 3 Acceptance Test — Client Launch Readiness Review` on the primary Google Calendar for August 27, 2026, from 2:00–3:00 PM in `America/Los_Angeles`. The provider event ID was independently read back and found active in a bounded search, and the user confirmed that the event was visible in their calendar. The event remains active until the user deletes it.

The Briefing Calendar Proposal Workflow is promoted from **Prototype** to **Tested** on the combined repository regression, synthetic lifecycle, provider read-back, active-search, and real-client evidence. This does not claim that the in-memory repository workflow itself owns durable operational state: persistent proposal, approval, and audit storage is the next milestone before live briefing retrieval expands.

## 2026-08-16 — Direct Google Calendar connector promoted to Tested

Added provider-neutral direct-calendar orchestration and a thin Google Calendar API v3 adapter. The governed path now checks calendar write access, creates with `events.insert`, performs an independent `events.get` read-back, compares canonical event semantics, and reports verification failure separately from execution failure.

Added duplicate-safe retry behavior using a caller-preserved Mission Control operation ID and a deterministic Google-safe event ID. A Google `409` response triggers read-back of that known ID rather than a blind second mutation. Added connector-state handling for wrong account, insufficient scope, expired authorization, temporary provider unavailability, missing read-back data, execution failure, and semantic verification failure.

The full regression suite passes **16 tests**, and a live acceptance run confirmed owner access to the connected primary Google Calendar. The authorized test event was created and independently read back with matching provider ID, title, description, attendees, visibility, transparency, conferencing state, and equivalent start/end instants. The event was then deleted, and a bounded active-calendar search confirmed it was absent.

The persistent user-facing acceptance run then created five separate work events on the primary Google Calendar for August 17–21, 2026, from 7:00 AM–5:30 PM in `America/Los_Angeles`. Independent provider reads and a bounded active-calendar search confirmed all five IDs, titles, descriptions, opaque status, and exact requested local start/end times. The user subsequently confirmed that all five events were visible in the calendar. The events were intentionally left active.

Direct Google Calendar Write is promoted from **Prototype** to **Tested** on this combined automated, provider-read-back, active-search, and real-client evidence. The connector surface's failure to expose Google's raw `start.timeZone` and `end.timeZone` response fields remains a hardening item before **Stable**, rather than a blocker to Tested maturity.

## 2026-08-16 — Calendar proposal reinforcement architecture

Ratified and documented the governed Calendar Service workflow for briefing-generated proposals. A proposal now has two required presentation points: inline with the correspondence or intelligence that establishes its value, and again in an approval queue with enough context to support an informed Approve, Edit, Reject, or Defer decision. Each part of the Expanded Intelligence Brief receives its own queue, and unresolved proposals carry forward into the final Part Three queue.

Documented the Calendar Service ownership boundary, renewed approval after edits, direct-connector and verified-ICS paths, authorized email delivery as a fallback distinct from calendar import, fail-loud verification, retry/idempotency expectations, auditability, and progressive delegation constraints.

The architecture clarification itself did not change runtime maturity. Later in the same validation cycle, the required real-client acceptance evidence was received as recorded below. GitHub Issue #1 was closed with that acceptance evidence on 2026-08-16.

Runtime-validation result: the Calendar Service regression suite passed all 3 tests, and a generated `America/Los_Angeles` Stage 1 ICS artifact passed internal validation, was delivered by email, and was successfully imported into Apple Calendar. The Calendar Event Schema / Service and ICS Export are promoted from **Prototype** to **Tested**. They are not yet **Stable**; direct-connector and routine-use validation remain future work.

## 2026-08-15 — Stage 1 scaffold

Initialized the canonical Mission Control OS pilot repository. Added the Calendar Service prototype backed by the maintained `icalendar` library, initial regression tests, the connector state model, implementation-state handoff, governing architecture summary, and capability registry.

The current system is intentionally narrow. The Calendar Service remains Prototype until its automated tests are executed and a generated `.ics` file passes a real calendar-client import test. Broader briefing, Gmail, RIE, MCOM, and other subsystem implementation should not begin until this vertical slice is validated.
