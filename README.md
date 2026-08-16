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

Stage 1 Calendar Service and ICS Export are Tested. Direct Google Calendar Write is also Tested after 16 passing regression tests, verified live creation/read-back, and user confirmation that five persistent work events appeared at the requested Pacific times. The next implementation slice is one governed briefing path.
