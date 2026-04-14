# ADR 0001: Derived-First Project Identity

## Status

Accepted

## Decision

Project Harness V1 will derive project identity from canonical repo root instead of introducing a new persisted project store.

## Why

- minimizes migration and rollback risk
- lets the new surface ship on top of current state
- keeps runtime ownership with existing stores

## Consequences

- some fields are computed on read
- historical grouping quality depends on good workspace and repo-root normalization
- a persisted project layer can be added later if V1 proves stable
