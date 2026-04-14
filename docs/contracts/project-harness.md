# Project Harness Contract

## Entities

### Project

- keyed by canonical repo root
- derived from existing draft, mission, telemetry, and memory stores
- may have persisted lifecycle metadata for name, goal, working directories, and archive state

### Cycle

- one draft lineage
- may have a launched mission
- may point to predecessor and successor cycles

### Evidence

- normalized summary over existing artifacts
- simple first, additive later

## Core API Shapes

### `ProjectSummaryView`

- `project_id`
- `name`
- `repo_root`
- `primary_working_directory`
- `workspace_count`
- `goal`
- `planned_task_count`
- `mode`
- `status`
- `active_cycle_id`
- `blocker`
- `next_action`
- `active_mission_id`
- `archived_at`
- `has_activity`
- `updated_at`

Status notes:
- `planning`, `ready`, `running`, `blocked`, `completed`, and `idle` remain derived from active cycle state
- `archived` is a lifecycle override from project metadata

### `ProjectCycleView`

- `cycle_id`
- `title`
- `status`
- `draft_id`
- `mission_id`
- `latest_plan_run_id`
- `latest_plan_version_id`
- `predecessor_cycle_id`
- `successor_cycle_id`
- `blocker`
- `next_action`
- `created_at`
- `updated_at`

### `ProjectEvidenceSummary`

- `status`
- `contract_summary`
- `verifier_summary`
- `artifact_summary`
- `stream_summary`
- `items`

### `ProjectHarnessView`

- `summary`
- `context`
- `cycles`
- `active_cycle_id`
- `active_cycle`
- `evidence`
- `docs_status`
- `policy_summary`
- `lifecycle`

Lifecycle notes:
- archive is soft hide from the default Projects list
- archived projects remain fetchable by id and listable with `include_archived=1`
- delete is only allowed for archived projects without draft or mission history
