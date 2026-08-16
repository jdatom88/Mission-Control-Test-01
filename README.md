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

Stage 1 Calendar Service and ICS Export are Tested. The direct Google Calendar path is a Prototype with 16 passing regression tests and partial live acceptance: creation, observable-semantic read-back, and authorized deletion passed, while exact stored IANA timezone read-back remains open in GitHub Issue #2.
