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

Stage 1 Calendar Service, ICS Export, and Direct Google Calendar Write are Tested. Stage 3 now contains a Prototype governed briefing-calendar proposal workflow with inline context, a reinforced approval queue, Approve/Edit/Reject/Defer, verified execution/fallback outcomes, and audit records. The full suite passes 26 tests; runtime acceptance is NEXT.
