# Stage 4 Persistence Decision

## Status

Accepted for the Stage 4 prototype. This is an implementation decision behind a replaceable Mission Control boundary, not a constitutional commitment to one database product.

## Decision context

The Tested Stage 3 briefing-calendar workflow keeps proposals and audit records in process memory. It cannot reliably restore deferred proposals, preserve completed decisions across restarts, or distinguish a new approval from an external operation whose final receipt was interrupted.

The Stage 4 store must be understandable by a solo maintainer, atomic around approval transitions, inspectable, inexpensive, and replaceable before broader briefing or connector work begins.

## Options considered

| Option | Advantages | Disadvantages | Stage 4 result |
|---|---|---|---|
| Structured JSON file | Minimal format and easy manual inspection | Multi-record transitions, optimistic concurrency, corruption detection, and crash recovery require custom database behavior | Not selected |
| SQLite | Standard-library support, transactions, schema constraints, local portability, simple backup, no service credentials | A local file alone does not provide multi-device cloud availability | Selected for the prototype |
| Hosted relational database | Shared cloud state and a direct path toward multi-device use | Adds hosting, credentials, network failure modes, cost, and operational maintenance before they are needed | Deferred |

## Decision

Use Python's maintained `sqlite3` standard-library adapter behind a `CalendarProposalStore` protocol.

Mission Control continues to own proposal, approval, execution, and recovery policy. SQLite owns commodity durability and transaction behavior. The workflow does not issue SQL and provider connectors do not know which storage adapter is active.

The initial schema stores:

- the latest canonical proposal version and status;
- source context and value rationale;
- complete event and destination data, including IANA timezone names when available;
- append-only semantic audit records;
- verified execution or ICS receipts; and
- a schema version for fail-loud compatibility checks.

OAuth credentials and provider tokens are explicitly excluded.

## Safety and recovery rules

1. The approved proposal version is durably changed to `execution_pending` before an external write begins.
2. `execution_pending` proposals are not returned to the active approval queue and cannot be approved a second time.
3. If the process stops before the final receipt is durable, restart exposes the proposal through an interrupted-execution queue.
4. Recovery runs only through an executor that explicitly implements duplicate-safe `recover` behavior. Otherwise Mission Control reports uncertainty and performs no retry.
5. Direct Google recovery reuses the proposal's deterministic operation ID and provider read-back behavior. ICS recovery regenerates the same deterministic artifact path and UID.
6. Proposal update and audit insertion occur in one SQLite transaction.
7. Optimistic version/status checks prevent a stale workflow instance from overriding a newer decision or issuing an external write.
8. Corrupt, incomplete, foreign, or schema-incompatible state fails loudly; it is never silently treated as an empty queue.
9. If the external write succeeds but final receipt persistence fails, Mission Control does not report completion. The durable state remains `execution_pending` for safe reconciliation.

## Consequences and limits

- The Stage 4 implementation is a **Prototype** until restart and runtime acceptance are completed.
- A SQLite file is appropriate for the present single-operator slice but is not itself a cloud synchronization strategy.
- Deployment must place the database on durable storage and include it in backup/restore procedures.
- A future hosted adapter may replace SQLite without changing the briefing approval contract.
- Full briefing automation, Gmail/EIS retrieval, multi-user infrastructure, background execution, and new calendar providers remain out of scope.

## Architecture-conflict assessment

No constitutional conflict was exposed. The decision follows the existing Commodity Capability Reuse, Solo-Operator, Human Agency, progressive-automation, thin-integration, and fail-loud rules. A future requirement for shared multi-device runtime state may justify a hosted adapter, but it does not require changing the current approval semantics.
