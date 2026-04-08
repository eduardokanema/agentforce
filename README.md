# AgentForce

Multi-agent mission orchestrator with spec-driven development, TDD enforcement, external review, and retry loops.

## Overview

AgentForce breaks complex software projects into discrete tasks defined in YAML/JSON spec files, then orchestrates AI agents to execute them with built-in quality gates:

- **Spec-driven** — Missions are defined as structured specs with goals, acceptance criteria, TDD requirements, and dependencies
- **TDD enforcement** — Every task can require tests to pass before moving forward
- **External review** — Completed tasks are reviewed by independent agents before approval
- **Retry loops** — Failed tasks automatically retry with feedback context
- **Human intervention** — Blocking issues escalate to humans when agents can't resolve them
- **State persistence** — Missions survive crashes and can be resumed from any point
- **Telemetry** — Cross-mission metrics track performance, quality, and efficiency

## Installation

Install directly from GitHub:

```bash
curl -fsSL https://raw.githubusercontent.com/eduardokanema/agentforce/main/scripts/install.sh | bash
```

Install from a local checkout:

```bash
pip install -e .
```

For local development and test runs:

```bash
python3.11 -m pip install -e ".[dev]"
python3.11 -m pytest -q
```

## Building

Builds are supported natively on both macOS and Linux with Python 3.11+.
PyInstaller does not cross-compile, so build on the target OS you want to ship.

Install build tooling:

```bash
python3.11 -m pip install -e ".[build]"
```

Build an sdist and wheel:

```bash
python3.11 -m build
```

Build a standalone binary with PyInstaller:

```bash
pyinstaller mission.spec
```

The GitHub Actions workflow in [`.github/workflows/build.yml`](.github/workflows/build.yml)
verifies tests, packaging, and the PyInstaller build on both `ubuntu-latest` and
`macos-latest`.

## Quick Start

### 1. Write a mission spec

Create a YAML file defining your mission:

```yaml
mission:
  name: "Build HTTP API Server"
  goal: "Create a FastAPI server with health checks and metrics"
  definition_of_done:
    - "All endpoints return correct responses"
    - "Tests pass with 80%+ coverage"
  caps:
    max_concurrent_workers: 2
    max_retries_per_task: 3
    max_wall_time_minutes: 120

tasks:
  - id: "01"
    title: "Project scaffolding"
    description: "Create FastAPI app with /health endpoint"
    acceptance_criteria:
      - "GET /health returns 200 with {status: ok}"
    tdd:
      test_file: "tests/test_health.py"
      test_command: "pytest tests/test_health.py -v"
      tests_must_pass: true
```

### 2. Start the mission

```bash
mission start my-mission.yaml
```

### 3. Run autonomously

```bash
python3 -m agentforce.autonomous <mission-id>
```

Or drive manually tick-by-tick using the engine API.

## CLI Commands

| Command | Description |
|---------|-------------|
| `mission start <spec>` | Start a new mission from a spec file |
| `mission status <id>` | Show mission progress and state |
| `mission list` | List all missions |
| `mission report <id>` | Detailed mission report |
| `mission resolve <id> <task> <msg>` | Resolve a human-blocked task |
| `mission fail <id> <task>` | Mark a task as permanently failed |
| `mission kill <id>` | Stop a mission |
| `mission metrics` | Show aggregated telemetry across missions |
| `mission serve [--port PORT]` | Start the web dashboard (default: http://localhost:8080) |

## Architecture

```
MissionSpec (YAML/JSON)
    |
    v
MissionEngine ──tick()──> [WorkerDelegation, ReviewerDelegation, HumanIntervention]
    |                           |                    |                    |
    v                           v                    v                    v
MissionState              Worker Agent          Reviewer Agent       Human User
(persistence)             (implements)          (validates)          (resolves)
```

### Core Components

- **`MissionEngine`** — State machine that drives missions via `tick()` cycles, returning delegation actions
- **`MissionSpec`** — Parses and validates mission definitions (YAML/JSON)
- **`MissionState`** — Persistent state tracking task progress, retries, caps, and events
- **`Memory`** — Cross-task context and lesson storage
- **`Telemetry`** — Aggregated metrics across missions

### Task Lifecycle

```
PENDING → IN_PROGRESS → COMPLETED → REVIEWING → REVIEW_APPROVED
                              ↓           ↓
                          RETRY ←── REVIEW_REJECTED
                              ↓
                        NEEDS_HUMAN → RETRY (after resolution)
                              ↓
                            FAILED
```

## Spec Format

Missions are defined in YAML with the following structure:

- **mission** — Name, goal, definition of done, and execution caps
- **tasks** — Individual work items with:
  - `id`, `title`, `description`
  - `acceptance_criteria` — Checklist for reviewers
  - `dependencies` — Task IDs that must complete first
  - `tdd` — Test file, command, and coverage thresholds
  - `output_artifacts` — Expected deliverables

See `missions/http-server.yaml` for a complete example.

## Programmatic API

```python
from agentforce.core.engine import MissionEngine
from agentforce.core.spec import MissionSpec

spec = MissionSpec.load_yaml("mission.yaml")
engine = MissionEngine.create(spec, state_dir="./state", memory=Memory("./memory"))

while not engine.is_done():
    actions = engine.tick()
    for action in actions:
        # Dispatch to agents, collect results
        result = dispatch(action)
        if isinstance(action, WorkerDelegation):
            engine.apply_worker_result(action.task_id, result.success, result.output)
        elif isinstance(action, ReviewerDelegation):
            engine.apply_reviewer_result(action.task_id, result.approved, result.feedback)
        elif isinstance(action, HumanIntervention):
            resolution = get_human_input(action.message)
            engine.apply_human_resolution(action.task_id, resolution)
```

## Data Storage

AgentForce stores state and telemetry in `~/.agentforce/`:

```
~/.agentforce/
├── state/          # Mission state files (JSON)
├── memory/         # Cross-task context and lessons
└── telemetry/      # Aggregated mission metrics
```

## Requirements

- Python 3.11+
- PyYAML (optional, for YAML spec support)

## License

MIT
