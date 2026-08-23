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

This is deployment-ready software acceptance, not proof of an actual encrypted Railway volume or provisioned R2 bucket. Account/billing authorization, infrastructure provisioning, volume-specific encryption evidence, provider retention controls, and a deployed clean restore rehearsal remain NEXT before operational reliance.

The Stage 4 storage tradeoffs, safety rules, and replacement boundary are documented in [Stage 4 Persistence Decision](docs/STAGE4_PERSISTENCE_DECISION.md).

The runtime configuration, backup cadence, restore procedure, fail-loud rules, and acceptance boundary are documented in [Pilot Runtime Durability Contract](docs/PILOT_RUNTIME_DURABILITY.md).

The selected provider topology and operator acceptance checklist are documented in [Railway + Cloudflare R2 Pilot Deployment](docs/RAILWAY_R2_DEPLOYMENT.md).
