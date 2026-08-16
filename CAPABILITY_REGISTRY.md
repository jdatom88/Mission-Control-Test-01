# Mission Control OS — Capability Registry

| Capability | Purpose | Engine / dependency | Maturity | Validation | Notes |
|---|---|---|---|---|---|
| Calendar Event Schema / Service | Centralize calendar event handling | Mission Control | Tested | 3 regression tests passed + emailed ICS imported successfully into Apple Calendar | Must be used by all calendar-producing subsystems |
| ICS Export | Universal interoperable calendar-file fallback | `icalendar` 7.x via thin adapter | Tested | Parse-back + artifact existence + successful Apple Calendar import | Never expose fake download state |
| Connector State Model | Distinguish healthy, empty, scope, account, auth, unavailable, execution-failure, and verification-failure states | Mission Control | Prototype | Google adapter regression tests pass; live connector-state tests pending | Shared by Calendar, Gmail, GitHub and future connectors |
| Direct Google Calendar Write | Lowest-friction event creation | Google Calendar API v3 via thin adapter | Tested | 16-test suite + five live `America/Los_Angeles` work events created, independently read back, found active at the requested local times, and confirmed visible by the user | Uses caller-preserved operation ID and Google-safe event ID for duplicate-safe retry; exact raw IANA-field retrieval remains a Stable-maturity hardening item |
| Briefing Calendar Proposal Workflow | Preserve source context, reinforce proposals, govern decisions, and route approved events through the Calendar Service | Mission Control | Tested | 10 focused workflow tests; full suite passes 26 tests; synthetic decision-path acceptance passed; live Google event was created, read back, found active, and confirmed visible by the user | Stage 3 acceptance is complete; workflow state remains in memory, with durable proposal/approval/audit state assigned to Stage 4 |
| Briefing Engine | Generate Mission Control briefing outputs | Mission Control reasoning layer | Designed, not implemented here | Future vertical slice | Stable chat behavior remains separate until intentionally migrated |
| Reinforcement Intelligence Engine | Prioritize high-value repeated knowledge exposure | Mission Control | Designed, not implemented | Future tests | Do not build during current calendar milestone |
| Operations Monitor | Detect meaningful work that has quietly stalled | Mission Control | Designed, not implemented | Future tests | Do not build during current calendar milestone |

## Maturity states

- **Designed** — architecture exists, no repository implementation yet.
- **Prototype** — implementation exists but has not completed acceptance testing.
- **Tested** — regression and real-world acceptance tests pass.
- **Stable** — tested capability is approved for routine use and protected by regression checks.
