# AgentForce

Multi-agent mission orchestrator with spec-driven development, AI review gates, a persistent execution daemon, and a web dashboard.

## Overview

AgentForce breaks complex software projects into discrete tasks defined in YAML spec files, then orchestrates AI agents to execute them autonomously:

- **Spec-driven** — Missions are YAML documents with goals, acceptance criteria, TDD requirements, dependencies, and execution caps
- **External review** — Every task is reviewed by an independent agent before approval; scores below 8/10 are automatically rejected
- **Retry loops** — Rejected tasks retry with reviewer feedback; security/TDD hard blocks escalate to human intervention
- **Persistent state** — Missions survive crashes and resume from any point via file-backed state in `~/.agentforce/`
- **Execution daemon** — A queue-based supervisor runs missions in the background, supporting concurrent workers and graceful drain on shutdown
- **Flight Director Cockpit** — Browser UI for planning, editing, and launching missions via a conversational AI planner
- **Telemetry** — Cross-mission metrics track cost, token usage, review scores, and retry rates

## Installation

```bash
pip install -e .
```

For development and tests:

```bash
pip install -e ".[dev]"
pytest -q
```

## Quick Start

### 1. Start the dashboard

```bash
mission serve --daemon
```

Open `http://localhost:8080`. The `--daemon` flag enables the embedded execution daemon so missions launched from the UI execute immediately without a separate process.

### 2. Create a mission via the Flight Director Cockpit

Navigate to **Flight Director** in the sidebar. Enter a prompt describing what you want to build, select a workspace directory and approved models, then click **Open Flight Plan**. The AI planner auto-generates a draft mission spec. Refine it through conversation, adjust tasks in the engineering controls panel, and click **Launch Mission**.

### 3. Or start a mission from a YAML spec

```bash
mission start my-mission.yaml
```

If the daemon is running (started with `--daemon`), the mission is queued immediately. Without the daemon, a one-shot `run_autonomous` subprocess is spawned per mission.

---

## The Execution Daemon

The daemon is a persistent supervisor that manages a queue of missions and executes them concurrently via `run_autonomous()`.

### Enabling the daemon

**Embedded mode** (recommended) — starts inside the dashboard server process:

```bash
mission serve --daemon
```

**Programmatic** — for embedding in other processes:

```python
from agentforce.server import serve
serve(port=8080, daemon=True)
```

### Daemon REST API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/daemon/status` | GET | Daemon state, queue, active missions, last heartbeat |
| `/api/daemon/enqueue` | POST | Queue a mission by `mission_id` |
| `/api/daemon/dequeue` | POST | Remove a pending mission from the queue |
| `/api/daemon/stop` | POST | Graceful drain — finish in-flight missions, accept no new work |

Mutating endpoints (`enqueue`, `dequeue`, `stop`) require the `X-Agentforce-Token` header when the `AGENTFORCE_TOKEN` environment variable is set.

```bash
# Check daemon status
curl http://localhost:8080/api/daemon/status

# Manually enqueue a mission
curl -X POST http://localhost:8080/api/daemon/enqueue \
  -H "Content-Type: application/json" \
  -d '{"mission_id": "abc123"}'
```

### How it works

- Each mission runs `run_autonomous()` in a dedicated thread
- The queue is persisted as JSONL at `~/.agentforce/daemon_queue.jsonl`; it survives server restarts
- A `fcntl` file lock (`~/.agentforce/daemon.lock`) prevents duplicate daemon instances in the same process
- `sys.exit()` calls inside `run_autonomous()` are caught so one mission cannot kill the daemon
- Graceful drain waits up to `max_drain_seconds` for in-flight missions to complete before stopping
- Mission caps (`max_concurrent_workers`, `max_wall_time_minutes`, `max_cost_usd`) are enforced per-mission as before

---

## CLI Commands

```
mission start <spec.yaml>          Start a mission from a YAML spec file
mission serve [--port N] [--daemon] Start the web dashboard (default port: 8080)
mission status <id>                 Show mission progress and task states
mission list                        List all missions
mission report <id>                 Detailed mission report with event log
mission pause <id>                  Pause a running mission
mission resume <id>                 Resume a paused mission
mission kill <id>                   Stop a mission (marks in-progress tasks blocked)
mission resolve <id> <task> <msg>   Resolve a human-blocked task with guidance
mission fail <id> <task>            Mark a human-blocked task as permanently failed
mission review <id>                 Run a retrospective AI review of a completed mission
mission metrics [--mission <id>]    Show aggregated telemetry across missions
```

Additional options for `mission start`:

```
--id <id>                 Override the generated mission ID
--workdir <path>          Override the working directory
--worker-model <model>    Override the worker model
--reviewer-model <model>  Override the reviewer model
```

---

## Running Missions Autonomously (without the daemon)

```bash
python3 -m agentforce.autonomous <mission-id>
```

Options:

```
--agent auto|claude|opencode   Agent connector (default: auto)
--model <model-id>             Model override
--variant low|medium|high      Reasoning effort (default: medium)
--extend-caps                  Ignore wall-time and retry limits for this run
--max-ticks N                  Supervisor loop tick limit (default: 2000)
```

Example — resume a mission that hit a wall-time cap:

```bash
python3 -m agentforce.autonomous --extend-caps abc123
```

---

## Mission Spec Format

```yaml
mission:
  name: "Build HTTP API Server"
  goal: "Create a FastAPI server with health checks and metrics"
  definition_of_done:
    - "All endpoints return HTTP 200 with correct JSON shapes"
    - "pytest tests/ passes with >= 80% coverage"
  caps:
    max_concurrent_workers: 2
    max_retries_per_task: 3
    max_retries_global: 10
    max_wall_time_minutes: 120
    max_cost_usd: 2.00
    review: enabled          # or "disabled" to skip the review gate
  execution_defaults:
    worker:
      agent: claude          # connector: claude or opencode
      model: claude-sonnet-4-6
      thinking: medium       # low | medium | high
    reviewer:
      agent: claude
      model: claude-sonnet-4-6
      thinking: low

tasks:
  - id: "01"
    title: "Project scaffolding"
    description: "Create FastAPI app structure with /health endpoint"
    acceptance_criteria:
      - "GET /health returns HTTP 200 with {\"status\": \"ok\"}"
      - "pytest tests/test_health.py passes"
    dependencies: []
    max_retries: 3
    output_artifacts:
      - "app/main.py"
      - "tests/test_health.py"
    tdd:
      test_file: "tests/test_health.py"
      test_command: "pytest tests/test_health.py -v"
      tests_must_pass: true
    execution:                     # optional per-task override of execution_defaults
      worker:
        model: claude-sonnet-4-6
        thinking: high

  - id: "02"
    title: "Add metrics endpoint"
    description: "Implement /metrics returning request counts"
    acceptance_criteria:
      - "GET /metrics returns HTTP 200 with JSON containing request_count > 0"
    dependencies: ["01"]
    max_retries: 2
    output_artifacts:
      - "app/metrics.py"
```

See `missions/` for real examples.

---

## Task Lifecycle

```
PENDING ──► IN_PROGRESS ──► COMPLETED ──► REVIEWING ──► REVIEW_APPROVED
                                │               │
                           (worker fail)   (score < 8)
                                │               │
                                └──────► RETRY ◄┘
                                            │
                                     (retries exhausted)
                                            │
                                     NEEDS_HUMAN ──► RETRY (after resolution)
                                            │
                                          FAILED
```

- `COMPLETED` — worker finished, awaiting reviewer dispatch
- `REVIEWING` — reviewer agent running
- `REVIEW_APPROVED` — score ≥ 8 and all criteria met; task is done
- `NEEDS_HUMAN` — security or TDD hard block, or retries exhausted with blocking issues
- The **Retry** button and **Restart Mission** work on `failed`, `blocked`, `review_rejected`, and `completed` (stuck) tasks, and re-enqueue to the daemon automatically

---

## Architecture

```
MissionSpec (YAML)
      │
      ▼
MissionEngine ──tick()──► [WorkerDelegation | ReviewerDelegation | HumanIntervention]
      │                          │                    │                    │
      ▼                          ▼                    ▼                    ▼
MissionState              Worker Agent          Reviewer Agent       Human (UI/CLI)
(~/.agentforce/state/)    (implements task)     (validates output)   (resolves block)

MissionDaemon
  ├── JSONL queue (~/.agentforce/daemon_queue.jsonl)
  ├── One thread per active mission
  └── REST API  /api/daemon/*

Dashboard (http://localhost:8080)
  ├── Mission list & detail pages
  ├── Task stream viewer (live agent output)
  ├── Flight Director Cockpit (plan mode)
  └── WebSocket live updates
```

### Core modules

| Module | Purpose |
|--------|---------|
| `agentforce.core.engine` | State-machine tick loop, action dispatch |
| `agentforce.core.spec` | MissionSpec / TaskSpec parsing and validation |
| `agentforce.core.state` | MissionState persistence and status queries |
| `agentforce.daemon` | MissionDaemon queue supervisor |
| `agentforce.autonomous` | `run_autonomous()` — supervisor loop that drives one mission end-to-end |
| `agentforce.server` | ThreadingHTTPServer dashboard + WebSocket |
| `agentforce.connectors` | Agent CLI adapters (claude, opencode) |
| `agentforce.memory` | Cross-task context and lessons storage |
| `agentforce.review` | Post-mission retrospective reviewer |
| `agentforce.telemetry` | Aggregated metrics store |

---

## Flight Director Cockpit (Plan Mode)

The Flight Director Cockpit is the browser UI for creating missions collaboratively with an AI planner.

1. Navigate to `http://localhost:8080` → **Flight Director**
2. Enter a mission prompt, select working directories, approved models, and a companion model
3. Click **Open Flight Plan** — the planner auto-generates an initial draft spec
4. Refine the plan by chatting with the planner on the left panel
5. Edit tasks directly in the Engineering Controls rail on the right:
   - Mission name, goal, and definition of done
   - Task titles, descriptions, acceptance criteria
   - Dependencies (checkbox grid — check which tasks must complete first)
   - Per-task worker and reviewer model overrides
   - Output artifacts
6. Click **Launch Mission** — the draft is finalized and enqueued on the daemon

---

## Data Storage

```
~/.agentforce/
├── state/                  # Mission state files (one JSON per mission)
├── streams/                # Live agent output logs (one .log per task)
├── memory/                 # Cross-task project memory
├── telemetry/              # Aggregated mission metrics
├── reviews/                # Post-mission retrospective reports
├── daemon_queue.jsonl      # Persistent execution queue
└── daemon.lock             # Exclusive daemon instance lock
```

---

## Requirements

- Python 3.11+
- Claude Code CLI (`claude`) or OpenCode CLI (`opencode`) for agent execution
- Optional: `keyring` for storing API keys (bundled as a dependency)
- Optional: `anthropic` Python SDK for direct HTTP fallback in the planner

## License

MIT
