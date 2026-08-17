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

Stage 1 Calendar Service, ICS Export, Direct Google Calendar Write, the Stage 3 governed briefing-calendar proposal workflow, and the Stage 4 persistent-state boundary are Tested. Stage 4 provides SQLite-backed, replaceable persistence for proposals, decisions, audit records, receipts, restart restoration, and duplicate-safe recovery. The full suite passes 41 tests, the five-process runtime acceptance passed twice with zero live calendar mutations, and canonical CI passed. Pilot runtime durability and backup/restore validation are NEXT.

The Stage 4 storage tradeoffs, safety rules, and replacement boundary are documented in [Stage 4 Persistence Decision](docs/STAGE4_PERSISTENCE_DECISION.md).
