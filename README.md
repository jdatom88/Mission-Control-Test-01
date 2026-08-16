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

Stage 1 Calendar Service, ICS Export, Direct Google Calendar Write, and the Stage 3 governed briefing-calendar proposal workflow are Tested. Stage 3 includes inline context, a reinforced approval queue, Approve/Edit/Reject/Defer, verified execution/fallback outcomes, and audit records. The full suite passes 26 tests, synthetic lifecycle acceptance passed, and a live Google event was independently read back and confirmed visible by the user. Persistent proposal, approval, and audit state is NEXT.
