# AgentForce Architecture

AgentForce is a local-first control plane for long-running AI software execution. The current system already has strong runtime primitives: mission specs, durable state, daemon-backed execution, review gates, planning runs, telemetry, and memory. `Project Harness V1` adds a derived project layer over those primitives without replacing them.

## Current Runtime Layers

1. `MissionSpec` and `TaskSpec` define executable work.
2. Planning routes and stores persist drafts, plan runs, and plan versions.
3. Mission routes and daemon flow launch, supervise, retry, and readjust execution.
4. Telemetry and memory provide cross-run visibility.
5. The React dashboard exposes planning, mission control, tasks, telemetry, settings, and Black Hole.

## Project Harness Overlay

`Project Harness V1` introduces a repo-root keyed view called a project.

- A project is derived from existing persisted records.
- A project groups planning and execution lineages for one workspace.
- A cycle represents one draft lineage and its launched mission, if any.
- Evidence is a normalized summary over existing plan, review, mission, and telemetry artifacts.

This keeps the architecture additive:

- existing stores remain source of truth
- missions remain executable units
- planning remains the draft/version pipeline
- the project layer becomes the primary operator-facing control surface

## V1 Design Constraints

- No migration of existing persisted state.
- Project identity is derived from canonical repo root.
- Black Hole is not part of the core Project Harness flow.
- Verification stays simple first: expose current evidence before inventing new storage.
- UI continuity matters more than new backend complexity.

## Intended Primary Flow

1. User opens Projects.
2. User selects a project harness.
3. User plans, launches, watches, readjusts, and verifies within one cockpit.
4. Deep mission and task pages remain available as drill-down surfaces.

## Extension Seams

- `ProjectMode`: `standard` now, `optimize` later.
- `MemoryProvider` / `RepoKnowledgeProvider`: optional future semantic memory sidecar.
- Evidence adapters: can be enriched later without changing the top-level project contract.
