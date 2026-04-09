---
name: mission-plan
description: Create or review AgentForce mission YAML specifications using a structured 6-phase interview, quality gate, and validation workflow. Use when the user wants to draft a new mission spec or review an existing one with /mission-plan or /mission-plan --review <path>.
disable-model-invocation: true
argument-hint: "[--review <spec.yaml>]"
---

# mission-plan Skill

Create high-quality AgentForce mission YAML specifications using a structured 6-phase interview, Code Principles quality gate, and auto-validation.

## Usage

```text
/mission-plan
/mission-plan --review path/to/spec.yaml
```

---

## Overview

This skill guides creation of AgentForce mission specs that consistently score 8.0+/10 on quality metrics. It enforces:
- **Code Principles:** YAGNI, Occam's Razor, Miller's Law (7 tasks max, 5 criteria max), SOLID/SRP, DRY, Safety First
- **Reviewer Dimensions:** Spec Compliance, Acceptance, TDD, Quality, Security, Edge Cases, Scope Creep, Contradictions
- **Task Discipline:** Single responsibility per task, concrete output artifacts, testable acceptance criteria

---

## Phase 1: Goal Clarification

**Purpose:** Extract mission name, goal statement, and Definition of Done (DoD).

**Conversation Flow:**

1. **Welcome & explain scope:**
   ```
   I'll help you create a high-quality AgentForce mission spec.

   First, let's clarify the goal. I'll ask three questions:
   1. What is the mission name? (keep it short: "HTTP Server", "Dark Mode", "Payment API")
   2. What is the primary goal? (one sentence: "Build a production-ready HTTP server with health checks and metrics")
   3. How will we know the mission is done? (Definition of Done: "Server runs on port 8080, health check /health returns 200 OK, metrics exported to Prometheus")
   ```

2. **Ask for mission name:**
   - If response < 3 words or > 5 words: ask for shorter name
   - Store as `spec.name`

3. **Ask for goal:**
   - If goal is vague ("Build something", "Implement it"): ask for specifics
   - If goal spans multiple unrelated areas: suggest splitting into follow-on missions
   - Store as `spec.goal`

4. **Ask for Definition of Done:**
   - **Critical check:** Reject vague DoD like "It works", "Fully implemented", "Done"
   - **Required:** Concrete, testable criteria. Examples:
     - ✅ "HTTP server listens on port 8080, responds to GET /health with 200 and {status: ok}"
     - ✅ "All tests pass, coverage > 90%, linting OK, no security warnings from bandit"
     - ✅ "Docker image builds and runs; README includes setup, usage, and API examples"
     - ❌ "It works"
     - ❌ "Feature is complete"
   - If rejected: explain what makes it concrete (observable, measurable, verifiable by tests or assertions)
   - Store as `spec.definition_of_done`

5. **Checkpoint:** Confirm understanding, then advance to Phase 2.

**Exit Criteria:**
- name, goal, definition_of_done all defined and concrete
- No vague language; all statements are testable

---

## Phase 2: Task Breakdown

**Purpose:** Decompose goal into concrete, single-responsibility tasks with dependencies.

**Conversation Flow:**

1. **Explain task discipline:**
   ```
   Each task should:
   - Have ONE reason to change (SOLID/SRP)
   - Produce one or more output artifacts
   - Be completable in 2–8 hours of worker time
   - Not overlap with other tasks

   Example: "HTTP Server" might break into:
   1. Project scaffolding with FastAPI
   2. Health check endpoint
   3. Metrics middleware
   4. Integration tests
   5. Docker support & README
   ```

2. **Prompt for task list:**
   - Ask: "What are the key work items?"
   - For each task, confirm:
     - **Name:** Clear, action-oriented (verb-noun: "Implement X", "Add Y", "Setup Z")
     - **SRP check:** "What would cause this task to change?" — if answer is >1 thing, split it
     - **Output artifact:** "What gets produced? Code file? API? Test suite?" — must be concrete
     - **Dependency:** "Does this task depend on another?" — document as `depends_on: [task_id]`

3. **Miller's Law check:**
   - If task count > 7: Ask user to prioritize top 7 and suggest follow-on mission for the rest
   - Enforce: max 7 tasks per mission

4. **Draw dependency DAG (ASCII):**
   ```
   01: Project scaffolding
   ↓
   02: Health check endpoint
   ├─ 03: Metrics middleware
   │  └─ 04: Integration tests
   └─ 05: Docker support
   ```

5. **SRP validation:**
   - For each task, ask: "Is this a single responsibility, or does it span multiple concerns?"
   - Examples of bad decomposition:
     - ❌ "Implement API endpoints and add caching" (two concerns)
     - ✅ "Implement GET /users endpoint" (one concern)

6. **Checkpoint:** Confirm task list, dependencies, and artifacts before Phase 3.

**Exit Criteria:**
- 1–7 tasks defined
- Each task has: name, description, output artifacts, dependencies
- Dependency DAG is acyclic (no circular deps)
- SRP validated for each task

---

## Phase 3: Criteria & TDD

**Purpose:** Define acceptance criteria (≤5 per task) and TDD specification.

**Conversation Flow:**

1. **For each task, ask:**
   ```
   Task: {task.name}

   What are the acceptance criteria? (max 5, each must be concrete & testable)
   Criteria are "DONE when":
   - Endpoint returns 200 OK for valid input
   - Endpoint returns 400 with error message for invalid input
   - Response time < 100ms for 100 requests/sec
   - All database queries are indexed
   - Health check endpoint created at /health
   ```

2. **Validate each criterion:**
   - **Check for vagueness:**
     - ❌ "Works well", "Is performant", "Good error handling"
     - ✅ "Returns 200 OK", "Response < 100ms", "Handles TypeError with 400 + message"
   - **Check for testability:** "Could a test or assertion verify this?" If yes, accept. If no, reject.
   - **DRY check:** Across all tasks, are any acceptance criteria duplicated? If yes, consolidate.

3. **TDD specification (for code-producing tasks):**
   - Ask: "What tests define success for this task?"
   - Require: Test file structure, test cases (at least 3: happy path, error case, edge case)
   - Example:
     ```python
     tests/test_health.py
     - test_health_check_returns_200_ok()
     - test_health_check_returns_json()
     - test_health_check_timeout()
     ```

4. **Checkpoint:** Confirm all criteria are concrete and testable before Phase 4.

**Exit Criteria:**
- 1–5 acceptance criteria per task, all concrete & testable
- TDD spec defined for code tasks (test file structure + test cases)
- No duplicate criteria across tasks (DRY)

---

## Phase 4: Caps & Config

**Purpose:** Define mission-level caps (concurrency, retries, cost, time) and working directory.

**Conversation Flow:**

1. **Ask for caps:**
   ```
   Mission caps (resource limits):

   - Max concurrent workers? (default: 2, range: 1–4)
     → How many workers should run tasks in parallel?

   - Max retries per task? (default: 2, range: 1–3)
     → If a task fails, how many times should we retry?

   - Wall time limit (minutes)? (default: 60, range: 30–240)
     → Maximum wall time before mission halts?

   - Max cost (USD)? (default: 0.50)
     → API cost limit before mission halts?

   - Working directory? (default: ./missions-{slug})
     → Where should mission files be created?
   ```

2. **Validate caps:**
   - **max_concurrent_workers:** 1–4 (more causes API rate-limit issues)
   - **max_retries_per_task:** 1–3 (more wastes time on failing tasks)
   - **max_wall_time_minutes:** 30–240 (too short: no time for complex tasks; too long: wasted time)
   - **max_cost_usd:** 0.01–1.00 (cost gate enforced at runtime; P0 improvement S-03)
   - **working_dir:** absolute path or relative to current dir

3. **Suggest defaults based on complexity:**
   - Task count 1–3: `workers=1, retries=2, wall_time=60, cost=0.25`
   - Task count 4–5: `workers=2, retries=2, wall_time=90, cost=0.50`
   - Task count 6–7: `workers=2, retries=3, wall_time=120, cost=0.75`

4. **Checkpoint:** Confirm caps match mission complexity before Phase 5.

**Exit Criteria:**
- All caps defined (workers, retries, wall_time, cost, working_dir)
- Caps are reasonable for task count and complexity
- Cost budget clearly understood by user (will halt mission if exceeded)

---

## Phase 5: Quality Gate

**Purpose:** Validate mission against Code Principles, reviewer dimensions, and output artifacts.

**Conversation Flow:**

### 5a: Code Principles Check

For each principle, apply to all tasks:

**1. Safety First**
```
□ No hardcoded credentials, API keys, passwords in task descriptions
□ Security-critical tasks explicitly marked (e.g., "credential handling")
□ No assumptions about external service availability without fallback

Issue found? → Ask user to remove credentials, add fallback plan, or mark as security task
```

**2. YAGNI (You Aren't Gonna Need It)**
```
□ No speculative tasks ("for future use", "might be useful", "could scale to")
□ Each task directly contributes to Definition of Done
□ No "extra features" beyond goal scope

Issue found? → Ask: "Does this task directly achieve the goal, or can we cut it?"
```

**3. Occam's Razor (Simplest Solution)**
```
□ Task DoD uses simplest approach (no premature optimization)
□ Acceptance criteria don't require multiple libraries/frameworks
□ Task scope is minimal: does one thing well

Issue found? → Challenge: "Could we achieve this DoD with less code/complexity?"
```

**4. Miller's Law (7±2 / 5±2)**
```
□ Max 7 tasks (already enforced in Phase 2)
□ Max 5 acceptance criteria per task
□ Max ~10 lines per task description

Issue found? → Already caught; skip if passed Phase 2
```

**5. SOLID / SRP (Single Responsibility)**
```
□ Each task has ONE reason to change
□ Task description doesn't mention unrelated concerns
□ Output artifacts are cohesive (same component/module)

Issue found? → Ask: "Could we split this task into two narrower tasks?"
```

**6. DRY (Don't Repeat Yourself)**
```
□ No duplicate acceptance criteria across tasks
□ No task duplicates another task's work
□ Shared setup documented (e.g., "requires project scaffolding from Task 01")

Issue found? → Consolidate duplicates or clarify dependency
```

### 5b: Reviewer Checklist Simulation

Simulate reviewer scoring (8 dimensions + Code Principles from 5a):

**SPEC COMPLIANCE**
```
□ Spec YAML format is valid (task ID, name, criteria, TDD, artifacts)
□ All required fields present (definition_of_done, acceptance_criteria, output_artifacts)
□ Caps are reasonable (wall_time > sum of task times)

Score 10: Complete and valid | Score 7: Minor issues | Score <7: Critical missing fields
```

**ACCEPTANCE**
```
□ Acceptance criteria are concrete, testable, observable
□ No vague language ("good", "well", "nice")
□ All criteria can be verified by tests or assertions

Score 10: All criteria are objectively testable
Score 7: Mostly testable, minor ambiguity | Score <7: Vague or unmeasurable
```

**TDD (Test-Driven Development)**
```
□ Each code-producing task has test structure (test file, test cases)
□ Tests cover happy path, error case, edge case (min 3 per task)
□ Tests can be written before code (testable APIs defined)

Score 10: Full TDD spec | Score 7: Partial (e.g., missing edge cases)
Score <7: No TDD or untestable API
```

**QUALITY**
```
□ Task definitions are clear (no ambiguity)
□ Output artifacts are well-defined (file names, formats)
□ Dependencies are correct (no broken chains)

Score 10: Crystal clear | Score 7: Minor ambiguity | Score <7: Confusing/unclear
```

**SECURITY**
```
□ No hardcoded secrets
□ External API dependencies are called out (e.g., "requires OpenAI API key")
□ Error handling covers security concerns (never leak stack traces with secrets)

Score 10: Security-aware | Score 7: Baseline | Score <7: Risky
```

**EDGE CASES**
```
□ DoD mentions timeout handling (e.g., "endpoint responds within 100ms")
□ DoD mentions error cases (e.g., "returns 400 if input invalid")
□ Tasks anticipate failures (e.g., "retry logic included")

Score 10: Comprehensive edge case coverage
Score 7: Most edge cases | Score <7: Ignores edge cases
```

**SCOPE CREEP**
```
□ Tasks don't drift beyond goal (e.g., "HTTP server" doesn't include "full ORM")
□ Each task is focused; no feature creep
□ Follow-on missions documented for out-of-scope work

Score 10: Tight scope | Score 7: Minor creep | Score <7: Bloated
```

**CONTRADICTIONS**
```
□ No task contradicts another (e.g., "use FastAPI" then "use Flask")
□ DoD doesn't contradict acceptance criteria
□ Caps don't conflict (e.g., max_retries doesn't exceed wall_time / avg_task_time)

Score 10: Fully consistent | Score 7: Minor conflict | Score <7: Major conflicts
```

### 5c: Estimated Reviewer Score

Sum scores across 8 dimensions + Code Principles (5a):
- **9+ avg:** Excellent. Proceed to Phase 6.
- **7–8.9 avg:** Good, but request clarification on flagged items. Loop back to relevant phase.
- **<7 avg:** Issues found. Ask user to revise and re-enter Phase 5.

**Scoring output example:**
```
CODE PRINCIPLES:
  Safety First:     10/10 ✓
  YAGNI:            9/10 ✓
  Occam's Razor:    8/10 (could simplify middleware setup)
  Miller's Law:     10/10 ✓
  SOLID/SRP:        9/10 ✓
  DRY:              10/10 ✓

REVIEWER SIMULATION:
  Spec Compliance:  10/10 ✓
  Acceptance:       8/10 (criteria 2 & 3 could be more specific)
  TDD:              9/10 ✓
  Quality:          9/10 ✓
  Security:         10/10 ✓
  Edge Cases:       8/10 (add timeout handling)
  Scope Creep:      10/10 ✓
  Contradictions:   10/10 ✓

═══════════════════════════════
ESTIMATED QUALITY SCORE:  9.1/10

Status: ✓ APPROVED for Phase 6
Feedback: Minor: Clarify acceptance criteria #2, add timeout handling.
```

**Exit Criteria:**
- Estimated score ≥ 7.0/10 (or user accepts lower score with acknowledgment)
- All blocking issues (code principles violations) addressed
- Ready for YAML generation

---

## Phase 6: Output & Finalization

**Purpose:** Generate YAML spec file, print DAG, and provide run command.

**Conversation Flow:**

1. **Generate YAML:**
   ```yaml
   mission:
     name: "HTTP Server"
     goal: "Build production-ready HTTP server with health checks and metrics"
     definition_of_done: "Server runs on port 8080, health check /health returns 200 OK with {status: ok}, metrics exported to Prometheus format"

     caps:
       max_concurrent_workers: 2
       max_retries_per_task: 2
       max_wall_time_minutes: 60
       max_cost_usd: 0.50
       working_dir: "./missions-http-server"

     tasks:
       - id: "01"
         name: "Project scaffolding with FastAPI"
         description: "Setup FastAPI project structure with dependencies, linting, and testing"
         definition_of_done: |
           - FastAPI project runs on port 8080
           - pytest installed and run passes
           - pylint/black configured and passing
           - main.py imports FastAPI successfully
         acceptance_criteria:
           - "Server starts: `python main.py` listens on 8080"
           - "Tests run: `pytest` output shows ≥1 test passing"
           - "Code formatted: `black --check .` returns 0"
           - "No linting errors: `pylint main.py` returns 0"
           - "requirements.txt contains fastapi and uvicorn"
         output_artifacts:
           - "main.py"
           - "requirements.txt"
           - "tests/test_main.py"
           - ".pylintrc"
         test_driven_development: |
           tests/test_main.py:
           - test_server_starts() — starts on 8080
           - test_health_endpoint_missing() — should fail until implemented
           - test_import_fastapi() — FastAPI imports cleanly

       - id: "02"
         name: "Health check endpoint"
         depends_on: ["01"]
         description: "Implement GET /health endpoint returning JSON status"
         definition_of_done: |
           - GET /health responds with 200 OK
           - Response is JSON: {"status": "ok"}
           - Response time < 10ms for 100 consecutive requests
         acceptance_criteria:
           - "Endpoint returns 200 OK for GET /health"
           - "Response body is {\"status\": \"ok\"}"
           - "Response includes Content-Type: application/json"
           - "Endpoint is idempotent (calling 10x returns same result)"
           - "Load test: 100 req/sec < 10ms p50"
         output_artifacts:
           - "main.py (updated with /health route)"
           - "tests/test_health.py (new)"
         test_driven_development: |
           tests/test_health.py:
           - test_health_returns_200() — status code 200
           - test_health_returns_json() — response is valid JSON
           - test_health_returns_ok_status() — status field is "ok"

       # ... (remaining tasks follow same structure)
   ```

2. **Print ASCII DAG:**
   ```
   01: Project scaffolding with FastAPI
   ├─ 02: Health check endpoint
   │  ├─ 03: Metrics middleware
   │  └─ 04: Integration tests
   │     └─ 05: Docker support & README
   └─ 06: [parallel] API error handling
   ```

3. **Save file:**
   - Write to `./missions/{slug}.yaml` where slug = mission name in lowercase, hyphens
   - Example: "HTTP Server" → `./missions/http-server.yaml`
   - Confirm file was written: `✓ Saved to ./missions/http-server.yaml`

4. **Print run command:**
   ```
   ✓ Spec generated and validated (score: 9.1/10)

   Run this mission:
     mission start ./missions/http-server.yaml

   Run autonomously:
     mission start ./missions/http-server.yaml
     mission autonomous http-server --agent opencode --model opencode/nemotron-3-super-free

   Or use Claude:
     mission autonomous http-server --agent claude --model claude-sonnet-4-6

   Review progress:
     mission status http-server
     mission report http-server

   Review after completion:
     mission review http-server
   ```

5. **Checkpoint complete:** Return to shell with success message.

**Exit Criteria:**
- YAML file written to `./missions/{slug}.yaml`
- File is valid YAML (can be parsed)
- All tasks and dependencies are present
- User has run command ready to copy-paste

---

## Review Mode: `/mission-plan --review path/to/spec.yaml`

If user provides existing spec file, skip Phases 1–4 and jump to Phase 5 (Quality Gate).

**Flow:**
1. Parse YAML file
2. If invalid: report parse error, exit
3. If valid: extract mission name, tasks, criteria
4. Run Phase 5 quality gate checks
5. Report findings in tabular format:
   ```
   REVIEW MODE: http-server.yaml

   [CODE PRINCIPLES]
   Safety First:     ✓ No hardcoded secrets
   YAGNI:            ✓ All tasks in scope
   Occam's Razor:    ⚠ Task 03 could use stdlib regex instead of regex library
   Miller's Law:     ✓ 5 tasks (< 7 limit)
   SOLID/SRP:        ✓ Each task has single concern
   DRY:              ✓ No duplicate criteria

   [REVIEWER SIMULATION]
   Spec Compliance:  ✓ 10/10
   Acceptance:       ⚠ 7/10 — Criteria #2 is vague ("good error handling")
   TDD:              ✓ 9/10
   Quality:          ✓ 9/10
   Security:         ✓ 10/10
   Edge Cases:       ⚠ 7/10 — Missing timeout handling in task 02
   Scope Creep:      ✓ 10/10
   Contradictions:   ✓ 10/10

   ═══════════════════════════════
   ESTIMATED SCORE: 8.6/10

   RECOMMENDATIONS:
   1. [PHASE 3] Clarify acceptance criteria #2: "good error handling" → specific HTTP codes (400, 500)
   2. [PHASE 3] Add timeout criterion to task 02: "response time < 100ms for 100 req/sec"
   3. [PHASE 2] Consider splitting task 03 into two: middleware setup + tests

   ✓ Spec is high quality. Ready to run:
     mission start ./missions/http-server.yaml
   ```

---

## Utilities

### Code Principles Reference

| Principle | Description | Example Violation |
|-----------|-------------|-------------------|
| **Safety First** | No hardcoded credentials, assumes explicit error handling | API key in code, no null checks |
| **YAGNI** | No speculative tasks ("might be useful later") | Task: "Build payment system for future monetization" |
| **Occam's Razor** | Simplest solution that meets DoD | Task uses 3 libraries when stdlib works |
| **Miller's Law** | Max 7 tasks, max 5 criteria per task | 10 tasks, 8 criteria per task |
| **SOLID/SRP** | Each task has ONE reason to change | Task: "Setup API and add caching" (two reasons) |
| **DRY** | No duplicate work across tasks | Two tasks both implement logging |

### Reviewer Dimensions Reference

| Dimension | Definition |
|-----------|-----------|
| **Spec Compliance** | YAML format valid, all required fields present |
| **Acceptance** | Criteria are concrete, testable, observable |
| **TDD** | Test structure defined, tests cover happy/error/edge cases |
| **Quality** | Definitions clear, artifacts well-defined, dependencies correct |
| **Security** | No hardcoded secrets, error handling secure, dependencies called out |
| **Edge Cases** | Timeouts, error cases, retry logic, failures anticipated |
| **Scope Creep** | Tasks stay in scope, no feature bloat, follow-ons documented |
| **Contradictions** | Tasks don't conflict, DoD ↔ criteria consistent, caps realistic |

---

## Example Mission Specs (Reference)

Located in `./missions/`:
- `http-server.yaml` — Simple 5-task HTTP server (good starting template)
- `mission-review.yaml` — Medium complexity, good acceptance criteria examples
- `platform-evolution.yaml` — Complex refactor with multi-phase dependencies
- `ui-extraction.yaml` — Component extraction pattern
- `ui-mission-control.yaml` — Dashboard interface
- `vector-memory.yaml` — Feature implementation with semantic search

---

## Implementation Notes

- **Phase transitions:** Never jump phases; enforce linear flow (1→2→3→4→5→6)
- **Phase 5 blocking:** If estimated score < 7.0, loop back to failing phase for revision
- **Vagueness detection:** Use regex patterns to catch common vague words: "good", "well", "nice", "implement", "fix", "clean", etc.
- **YAML generation:** Use PyYAML or similar; ensure proper indentation and valid syntax
- **File I/O:** Confirm file write success; warn if file will overwrite existing spec
- **Review mode:** If no quality issues found, skip recommendations; just confirm ready to run

---

**Skill version:** 1.0
**Last updated:** 2026-04-09
**Reference:** /Users/rent/Projects/agentforce/docs/IMPROVEMENTS.md
