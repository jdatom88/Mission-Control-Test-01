# Mission Control OS

Mission Control OS is a governed personal executive operating system designed to reduce friction between knowing, deciding, and doing.

This repository is the canonical implementation workspace for the Mission Control pilot.

## Initial architecture

- Mission Control core package
- Centralized Calendar Service
- Connector state model
- Capability registry
- Regression tests

## Engineering principles

- Human agency first
- Progressive automation
- Fail loud; never fake completion
- Commodity capability reuse
- Thin, replaceable integration layers
- Solo-operator maintainability

## Current milestone

Stage 1 Calendar Service, ICS Export, Direct Google Calendar Write, the Stage 3 governed briefing-calendar proposal workflow, and the Stage 4 persistent-state boundary are Tested. Stage 4 provides SQLite-backed, replaceable persistence for proposals, decisions, audit records, receipts, restart restoration, and duplicate-safe recovery.

The approved pilot durability controls are merged into canonical `main` through PR #10. Explicit marked-volume bootstrap, no-create normal startup, write and integrity checks, SQLite online backup, no-overwrite publication, and clean semantic restoration have passed host-neutral acceptance.

Railway is selected as the single-instance pilot host and Cloudflare R2 as the independent S3-compatible backup target. The deployment integration adds full-object backup read-back, SHA-256 and semantic verification, safe offsite fetch, a fail-loud storage guardian, Docker packaging, and Railway config-as-code. The complete repository suite passes 65 tests and both separate-process acceptance harnesses remain green with zero live calendar mutations.

Railway health, private R2 upload/read-back, fail-loud storage behavior, and clean zero/non-empty restore rehearsals have passed. Pilot Runtime SQLite Durability remains Prototype because paid Railway snapshots, R2 retention controls, volume-specific encryption evidence, and routine-use evidence remain pending; the operator has deliberately deferred those subscription-dependent gates.

The governed Google Calendar read path for briefings is Tested. It performs a fresh bounded retrieval, maps timed and all-day events, distinguishes healthy empty data from failures, separates runtime-capability limitations from provider outages, and bounds transient retries. Twenty-one new tests pass, with **86 tests** green repository-wide and canonical CI #23/#24/#25 successful. Live bounded data retrieval, independent ID read-back, and an explicit healthy empty-window read passed with zero mutations. Full briefing-engine consumption and routine-use evidence remain prerequisites for Stable.

The Calendar Runtime Assembly is Tested. Its thin boundary performs a fresh read, renders current calendar context plus inline proposals and the reinforced approval queue, and delegates durable decisions and execution to the existing Tested workflow. Eight focused tests and **94 repository tests** pass. The combined synthetic acceptance verifies read-to-queue composition, all four decisions, verified execution, restart restoration, and zero live calendar mutations; canonical CI #31 passed. The current calendar implementation track is closed at Tested. This does not claim a full Briefing Engine or Stable maturity.

The Stage 4 storage tradeoffs, safety rules, and replacement boundary are documented in [Stage 4 Persistence Decision](docs/STAGE4_PERSISTENCE_DECISION.md).

The runtime configuration, backup cadence, restore procedure, fail-loud rules, and acceptance boundary are documented in [Pilot Runtime Durability Contract](docs/PILOT_RUNTIME_DURABILITY.md).

The selected provider topology and operator acceptance checklist are documented in [Railway + Cloudflare R2 Pilot Deployment](docs/RAILWAY_R2_DEPLOYMENT.md).
