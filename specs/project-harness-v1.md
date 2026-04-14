# Project Harness V1 Spec

## Problem

AgentForce currently makes users jump between draft, mission, task, telemetry, and special-mode surfaces. Long-running work needs one simpler control plane.

## Solution

Introduce a project harness keyed by repo root. It becomes the main surface for visibility, planning continuity, and lightweight validation.

## Requirements

### Shared Contract

- frontend and backend share the same project-harness payload model
- V1 mode defaults to `standard`

### Projects Inbox

- list derived projects
- show status, blocker, next action, active mission, and updated time

### Project Cockpit

- show `Now`, `Next`, `Evidence`, `Plan`, `Run`, and `History`
- keep planning and launched mission continuity in one route

### Evidence

- summarize current contract, verifier, artifacts, and stream status
- stay additive over current stores

## Validation

- route tests for project endpoints
- UI tests for project list and cockpit continuity
- smoke test using real local server
