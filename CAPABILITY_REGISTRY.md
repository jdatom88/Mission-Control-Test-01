# Mission Control OS — Capability Registry

| Capability | Purpose | Engine / dependency | Maturity | Validation | Notes |
|---|---|---|---|---|---|
| Calendar Event Schema / Service | Centralize calendar event handling | Mission Control | Prototype | Unit/regression tests + real import test | Must be used by all calendar-producing subsystems |
| ICS Export | Universal interoperable calendar-file fallback | `icalendar` 7.x via thin adapter | Prototype | Parse-back + artifact existence + real client import | Never expose fake download state |
| Connector State Model | Distinguish healthy, empty, scope, account, auth, unavailable, execution-failure states | Mission Control | Prototype | Connector-specific integration tests | Shared by Calendar, Gmail, GitHub and future connectors |
| Direct Google Calendar Write | Lowest-friction event creation | Google Calendar connector/API | Planned | Create + read-back verification | Build after Calendar Service vertical slice passes |
| Briefing Engine | Generate Mission Control briefing outputs | Mission Control reasoning layer | Designed, not implemented here | Future vertical slice | Stable chat behavior remains separate until intentionally migrated |
| Reinforcement Intelligence Engine | Prioritize high-value repeated knowledge exposure | Mission Control | Designed, not implemented | Future tests | Do not build during current calendar milestone |
| Operations Monitor | Detect meaningful work that has quietly stalled | Mission Control | Designed, not implemented | Future tests | Do not build during current calendar milestone |

## Maturity states

- **Designed** — architecture exists, no repository implementation yet.
- **Prototype** — implementation exists but has not completed acceptance testing.
- **Tested** — regression and real-world acceptance tests pass.
- **Stable** — tested capability is approved for routine use and protected by regression checks.
