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

The approved pilot durability controls are now implemented on the feature branch. Explicit marked-volume bootstrap, no-create normal startup, write and integrity checks, SQLite online backup, no-overwrite publication, and clean semantic restoration have 14 focused tests. The complete repository suite passes 55 tests, a separate-process loss/restore acceptance passed with zero live calendar mutations, and canonical GitHub Actions run #10 passed.

This is host-neutral software acceptance, not proof of an actual encrypted cloud volume or independent backup service. Selecting and provisioning the pilot cloud runtime, configuring external backup scheduling and retention, and completing a clean restore rehearsal on that infrastructure remain NEXT before operational reliance.

The Stage 4 storage tradeoffs, safety rules, and replacement boundary are documented in [Stage 4 Persistence Decision](docs/STAGE4_PERSISTENCE_DECISION.md).

The runtime configuration, backup cadence, restore procedure, fail-loud rules, and acceptance boundary are documented in [Pilot Runtime Durability Contract](docs/PILOT_RUNTIME_DURABILITY.md).
