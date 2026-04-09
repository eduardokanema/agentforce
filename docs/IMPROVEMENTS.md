# AgentForce: 18 Priority Improvements

## Executive Summary

Based on analysis of the "Build CLI HTTP Server" mission (ANALYSIS_2026_04_09.md), both multi-agent (8.25/10) and single-shot (7.94/10) approaches have **critical gaps in Token Economy** (both scored 4.0–5.0/10). This document outlines 18 concrete, grounded improvements organized by priority and implementation wave.

### Key Findings

- **Token Economy is Critical Gap**: Token tracking infrastructure exists (TokenLedger, TaskState fields) but is never instantiated or wired
- **Reviewer Quality lacks calibration**: Prompt contains 8 dimensions but no Code Principles dimension and no score anchors (why is 9.0 good vs. 10.0?)
- **Worker Guidance is implicit**: Worker prompt lacks explicit Code Principles guidance; quality rules must be inferred
- **Memory infrastructure is incomplete**: VectorMemory semantic query (top_k=8) fully implemented but never activated in engine.py
- **Spec validation is absent**: Mission specs contain no quality gate for Definition of Done or acceptance criteria clarity

---

## P0 — Token Economy (Critical)

Both approaches scored **4.0–5.0/10**. This is the highest-impact improvement area.

| ID | Title | Effort | Impact | Key Files |
|----|-------|--------|--------|-----------|
| S-01 | Wire TokenLedger into autonomous.py | Small | Critical | `autonomous.py`, `core/token_ledger.py` |
| S-02 | Parse Codex token events before discarding structure | Small | Critical | `connectors/codex.py`, `autonomous.py` |
| S-03 | Enforce `max_cost_usd` budget gate in check_caps() | Small | High | `core/state.py` (depends on S-01+S-02) |
| S-04 | Session caching for reviewer agents | Small | High | `autonomous.py` |
| S-05 | Cost-aware per-task model selection | Medium | Medium | `core/spec.py`, `core/engine.py` |

### Root Causes

1. **TokenLedger never instantiated** (token_ledger.py exists but is never called)
   - TaskState.tokens_in, tokens_out, cost_usd always remain 0
   - Cost tracking infrastructure complete but disconnected

2. **Codex token events formatted as human-readable strings**
   - Connectors/codex.py line ~80: tokens reported as "12.5K tokens" instead of structured {in: 12500, out: 0}
   - Orchestrator receives string, can't parse before passing to TaskState

3. **Budget cap never checked**
   - state.py:check_caps() evaluates wall_time and retries but ignores max_cost_usd
   - Mission can exceed budget without halt

4. **Reviewer session caching explicitly disabled**
   - autonomous.py line: `session_id = session_ids.get(tid) if role == "worker" else None`
   - Reviewers run stateless despite session_ids dict being available
   - Lost opportunity for review continuity and context reuse

### Expected Impact

- **S-01+S-02+S-03**: Mission cost reports become accurate; cost overruns are caught; Token Economy score increases to 8.0+/10
- **S-04**: Reviewer quality improves (fewer context resets); token efficiency improves (session reuse)
- **S-05**: Per-task model selection allows faster tasks on cheaper models (GPT-4o for simple logic, Claude for complex reasoning)

### Reliable Foundation

- TokenLedger: Already fully implemented, just needs wiring (YAGNI violation to build anew)
- Codex parsing: Similar pattern exists in OpenCode connector; replicate there
- Budget gates: Existing pattern in wall_time check (state.py check_caps) — extend to cost
- Session caching: OpenAI SDK pattern; widely used in production (Anthropic Workbench, Claude.ai)

---

## P1 — Reviewer Quality & Calibration

Reviewer prompt (core/spec.py lines 100–141) contains 8 checklist dimensions but lacks Code Principles and score anchors.

| ID | Title | Effort | Impact | Key Files |
|----|-------|--------|--------|-----------|
| S-06 | Add Code Principles as 9th reviewer checklist dimension | Small | High | `core/spec.py:generate_reviewer_prompt()` |
| S-07 | Per-criterion weighting (security/TDD as hard blocks) | Small | Medium | `autonomous.py:_enforce_review_thresholds()` |
| S-08 | Score calibration rubric (8=Good, 9=Excellent, 10=Perfect) | Tiny | Medium | `core/spec.py:generate_reviewer_prompt()` |
| S-18 | Output artifact verification in reviewer prompt | Tiny | Medium | `core/spec.py:generate_reviewer_prompt()` |

### Root Cause

Uniform 9.0/10 scores across tasks suggest reviewer cannot differentiate "meets bar" from "exceeds bar". Prompt contains acceptance, TDD, quality, security, edge cases, scope, contradictions — but:
- No Code Principles dimension (YAGNI, Miller's Law, SOLID, DRY, Occam's Razor, Safety First)
- No anchors: "What makes a 9 different from an 8?"
- No explicit artifact verification: task may complete without outputs

### Expected Impact

- **S-06**: Quality scores become more discriminating; workers see alignment with Code Principles; overall score improves 0.3–0.5 points
- **S-07**: Security and TDD violations caught consistently; hard blocks prevent low-quality approvals
- **S-08**: Score variance increases (healthy — shows reviewer is calibrated); consistency improves (80th percentile become 85th+)
- **S-18**: Tasks without outputs are rejected; reduces rework and increases first-pass rate

### Reliable Foundation

- Code Principles framework: Already fully documented in ANALYSIS_2026_04_09.md
- BARS scales (Behaviorally Anchored Rating Scales): Industry standard for rater calibration (used in 360° feedback, performance management)
- Per-criterion weighting: Pattern exists in OpenAI rubrics; standard LLM evaluation practice

---

## P2 — Worker Prompt Engineering

Worker prompt (core/spec.py lines 70–98) provides task context, criteria, and TDD spec but lacks explicit quality guidance.

| ID | Title | Effort | Impact | Key Files |
|----|-------|--------|--------|-----------|
| S-09 | Inject Code Principles reminder into worker prompt | Tiny | High | `core/spec.py:generate_worker_prompt()` |
| S-10 | Pre-computed task templates for common patterns | Medium | Medium | `core/spec.py`, new `agentforce/templates/` |

### Root Cause

Workers must infer "simplest solution" and "no hardcoded credentials" without explicit guidance. This is a "shift left" opportunity: catch YAGNI/Miller violations at generation time, not at review time.

### Expected Impact

- **S-09**: Workers self-correct on common violations (e.g., over-engineering, hardcoded values); review rejection rate drops 10–15%; first-pass rate increases
- **S-10**: Workers can reuse patterns (API client scaffolds, test templates); task completion time decreases; consistency increases

### Reliable Foundation

- Prompt injection: Proven in Claude API cookbook (system prompt best practices)
- Task templates: Pattern libraries widely used (Hugging Face templates, AWS CloudFormation snippets, Terraform modules)

---

## P3 — Memory & Context Optimization

VectorMemory semantic query implemented but never activated in engine.py.

| ID | Title | Effort | Impact | Key Files |
|----|-------|--------|--------|-----------|
| S-11 | Use VectorMemory query param with task description | Tiny | High | `core/engine.py` lines 271, 308 (one-line fix each) |
| S-12 | Extend outcome memory beyond 500-char truncation | Small | Medium | `core/engine.py:apply_reviewer_result()` |
| S-13 | Memory compression for long-running missions | Small | Low | `memory/memory.py`, `autonomous.py` |

### Root Cause

engine.py calls `memory.agent_context(mission_id, task_id)` without `query=` argument. VectorMemory.agent_context() falls back to full dump (all outcomes, all task descriptions) when query is absent. Semantic retrieval (top_k=8) is fully implemented but never used.

**Example (engine.py line 271):**
```python
# Current (dumps full memory):
ctx = memory.agent_context(mission_id, task_id)

# Should be:
ctx = memory.agent_context(mission_id, task_id, query=task.acceptance_criteria)
```

### Expected Impact

- **S-11**: Context becomes task-specific; token usage drops 20–30%; latency improves; quality scores stable (semantic search preserves relevant examples)
- **S-12**: Outcome summaries capture nuance (why rejected, specific failures); memory is more actionable
- **S-13**: Long missions (20+ tasks) maintain stable context window; memory system scales beyond 10–15 task limit

### Reliable Foundation

- VectorMemory: Already fully implemented (top_k, semantic search complete)
- Query params: Standard information retrieval pattern (Elasticsearch, Pinecone, Claude API embeddings all use same pattern)

---

## P4 — Mission Spec Design & Orchestration

No quality validation at spec load time; unclear Definition of Done and acceptance criteria lead to rework.

| ID | Title | Effort | Impact | Key Files |
|----|-------|--------|--------|-----------|
| S-14 | DoD quality validation at spec load time | Small | High | `core/spec.py:validate_quality()`, `cli/cli.py` |
| S-15 | Acceptance criteria quality validation | Small | High | `core/spec.py:validate_quality()` |
| S-16 | Smarter retry strategy (backoff + model escalation) | Medium | Medium | `core/spec.py:Caps`, `autonomous.py` |
| S-17 | Dynamic caps suggestion based on mission complexity | Small | Medium | `core/spec.py:suggest_caps()`, `cli/cli.py` |

### Root Cause

Mission specs are never validated for clarity. Vague DoD like "It works" or acceptance criteria like "Implement the feature" slip through to workers, causing reviewer rejection and rework.

### Expected Impact

- **S-14 + S-15**: Vague specs rejected at `mission start` with specific guidance; prevents 20–30% of rework cycles; first-pass rate increases
- **S-16**: Failed tasks retry with backoff (exponential, jitter) or escalate to better model; reduces thrashing on hard tasks; wall time improves
- **S-17**: Operator sees recommended caps (workers, retries, wall_time) based on task count and complexity; missions fail fast on bad caps instead of timing out

### Reliable Foundation

- Quality validation: Pattern exists in OpenAPI schema validation; implement similar for DoD/acceptance criteria
- Backoff + escalation: Standard pattern in distributed systems (gRPC, AWS SDK, Lambda retries)
- Complexity-based caps: Used in CI/CD (GitHub Actions job timeouts based on complexity, resource estimates)

---

## Implementation Wave Order

Prioritize by dependency and ROI.

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WAVE 1 — Zero-risk, high ROI (1-line or prompt additions)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 S-11  Use VectorMemory query param                    (core/engine.py)
       Effort: Tiny  |  Impact: High  |  Risk: None
       Change: Add query= param to agent_context() calls (lines 271, 308)

 S-08  Score calibration rubric in reviewer prompt    (core/spec.py)
       Effort: Tiny  |  Impact: Medium  |  Risk: None
       Change: Add anchor examples to generate_reviewer_prompt()

 S-09  Code Principles reminder in worker prompt       (core/spec.py)
       Effort: Tiny  |  Impact: High  |  Risk: None
       Change: Inject "apply Code Principles" guidance to generate_worker_prompt()

 S-18  Artifact verification in reviewer prompt        (core/spec.py)
       Effort: Tiny  |  Impact: Medium  |  Risk: None
       Change: Add explicit artifact checklist to reviewer checklist

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WAVE 2 — Token economy foundation (3–4 days)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 S-01  Wire TokenLedger into autonomous.py            (autonomous.py)
       Effort: Small  |  Impact: Critical  |  Dependency: None
       Change: Instantiate TokenLedger in mission startup; call update() after each API call

 S-02  Parse Codex token events before discarding    (connectors/codex.py, autonomous.py)
       Effort: Small  |  Impact: Critical  |  Dependency: None
       Change: Convert "12.5K tokens" → {in: 12500, out: 0} struct in codex.py

 S-03  Enforce max_cost_usd budget gate               (core/state.py)
       Effort: Small  |  Impact: High  |  Dependency: S-01, S-02
       Change: Update check_caps() to evaluate cost_usd > max_cost_usd

 S-04  Session caching for reviewer agents           (autonomous.py)
       Effort: Small  |  Impact: High  |  Dependency: None
       Change: Remove `else None` from reviewer session_id assignment

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WAVE 3 — Quality improvement (2–3 days)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 S-06  Add Code Principles as 9th reviewer dimension  (core/spec.py)
       Effort: Small  |  Impact: High  |  Dependency: None
       Change: Add Code Principles checklist to generate_reviewer_prompt()

 S-07  Per-criterion weighting (hard blocks)          (autonomous.py)
       Effort: Small  |  Impact: Medium  |  Dependency: None
       Change: Create _enforce_review_thresholds() with per-criterion weights

 S-14  DoD quality validation                          (core/spec.py, cli/cli.py)
       Effort: Small  |  Impact: High  |  Dependency: None
       Change: Add validate_quality() method; call from cli start

 S-15  Acceptance criteria validation                 (core/spec.py, cli/cli.py)
       Effort: Small  |  Impact: High  |  Dependency: None
       Change: Validate concrete + testable language; reject vague criteria

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WAVE 4 — Optimization (varies)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 S-05  Cost-aware per-task model selection           (core/spec.py, core/engine.py)
       Effort: Medium  |  Impact: Medium  |  Dependency: None
       Change: Add optional task.model_preference field; let workers optimize model choice

 S-10  Pre-computed task templates                    (core/spec.py, agentforce/templates/)
       Effort: Medium  |  Impact: Medium  |  Dependency: None
       Change: Build template library for common task patterns (API scaffolds, tests)

 S-12  Extend outcome memory beyond 500-char         (core/engine.py)
       Effort: Small  |  Impact: Medium  |  Dependency: None
       Change: Increase truncation limit; or implement progressive summarization

 S-13  Memory compression for long-running           (memory/memory.py, autonomous.py)
       Effort: Small  |  Impact: Low  |  Dependency: None
       Change: Compress old task outcomes; reindex for semantic search

 S-16  Smarter retry strategy                         (core/spec.py, autonomous.py)
       Effort: Medium  |  Impact: Medium  |  Dependency: None
       Change: Add exponential backoff; allow retry model escalation

 S-17  Dynamic caps suggestion                        (core/spec.py, cli/cli.py)
       Effort: Small  |  Impact: Medium  |  Dependency: None
       Change: Add suggest_caps() function; call from cli start
```

---

## Critical Files Reference

| File | Current State | Changes Required | Priority |
|------|---------------|------------------|----------|
| `agentforce/core/spec.py` | 250 lines | Worker prompt (S-09), reviewer prompt (S-06, S-07, S-08, S-18), DoD validation (S-14, S-15), task model field (S-05), suggest_caps() (S-17) | P1 |
| `agentforce/core/engine.py` | 350 lines | VectorMemory query (S-11), outcome memory (S-12) | P1 |
| `agentforce/core/state.py` | 180 lines | Cost budget gate in check_caps() (S-03) | P0 |
| `agentforce/core/token_ledger.py` | 80 lines | No changes — already correct, just needs wiring | — |
| `agentforce/autonomous.py` | 400+ lines | TokenLedger wire (S-01), reviewer sessions (S-04), per-criterion weighting (S-07), retry strategy (S-16) | P0 |
| `agentforce/connectors/codex.py` | 150 lines | Token event parsing (S-02) | P0 |
| `agentforce/cli/cli.py` | 380 lines | Quality validation warnings (S-14, S-15), suggest_caps flag (S-17) | P1 |
| `agentforce/memory/memory.py` | 200 lines | Memory compression (S-13) | P4 |
| `agentforce/templates/` | New dir | Task template library (S-10) | P4 |

---

## Verification Plan

### Token Economy (P0)

**S-01, S-02, S-03 verification:**
```bash
# Run short mission
mission start missions/http-server.yaml --id token-test

# Check non-zero cost in state
mission status token-test --json | jq '.task_states | .[] | .cost_usd'
# Expected: non-zero values (e.g., 0.0025, 0.0045)
```

**S-04 verification:**
Enable verbose logging; confirm reviewer session_id is not None:
```python
# In autonomous.py, add log:
logger.debug(f"Reviewer session_id: {session_id}")
# Expected: session_id = "sess_abc123..." (not None)
```

### Reviewer Quality (P1)

**S-06, S-08 verification:**
Submit task with function using 10 parameters:
```python
def complex_fn(a, b, c, d, e, f, g, h, i, j):
    return sum([a, b, c, d, e, f, g, h, i, j])
```
- Expected: Reviewer score < 8, feedback cites Miller's Law (max 5 params)

**S-18 verification:**
Create task with no output_artifact field:
- Expected: Reviewer score < 7, feedback requests artifact definition

### Memory Optimization (P3)

**S-11 verification:**
Enable verbose logging in engine.py:
```python
logger.debug(f"agent_context query: {task.acceptance_criteria}")
```
Run mission; confirm query is passed:
```
agent_context query: Implement health check endpoint returning {...}
```

### Spec Quality (P4)

**S-14, S-15 verification:**
Try to create mission with vague DoD:
```yaml
tasks:
  - name: "Implement feature"
    definition_of_done: "It works"
```
- Expected: `mission start` prints warning and exits with status 1
- Guidance: "Definition of Done is too vague. Expected format: 'HTTP 200 response with {...}'"

---

## Expected Impact Summary

| Metric | Current | Target | Source |
|--------|---------|--------|--------|
| Token Economy score | 4.0–5.0/10 | 8.0+/10 | S-01, S-02, S-03, S-04 |
| Overall Quality score | 8.1/10 (avg) | 8.8+/10 | S-06, S-07, S-08, S-09, S-14, S-15 |
| First-pass rate | ~60% | 75%+ | S-06, S-08, S-09, S-14, S-15 |
| Review rejection rate | ~15–20% | 5–10% | S-06, S-07, S-18 |
| Avg tokens/task | Unmeasured | 30–40% lower | S-11, S-04 |
| Spec validation issues | 0 | ~50% caught pre-flight | S-14, S-15 |

---

## Appendix: Reliable Foundations

### Constitution AI & Code Principles

Code Principles (YAGNI, Occam's Razor, Miller's Law, SOLID, DRY, Safety First) are derived from:
- **YAGNI**: XP (eXtreme Programming), refactored in pragmatic engineering culture
- **Occam's Razor**: Philosophy of science; applied to software via "simplest thing that could possibly work"
- **Miller's Law (7±2)**: Cognitive science; widely applied to API design, menu depth, function complexity
- **SOLID**: Object-oriented design (Martin, 2000); foundational in large systems
- **DRY**: Pragmatic Programmer; standard in all modern development
- **Safety First**: Constitution AI, Anthropic guidelines; embedded in Claude system prompts

### BARS Rating Scales

Behaviorally Anchored Rating Scales (Latham & Wexley, 1977) are gold standard for LLM rater calibration:
- Used in 360° feedback, performance management, compliance auditing
- Anchor examples prevent rater drift
- 5-point or 10-point scales with specific behavioral anchors (8=Meets, 9=Exceeds, 10=Exceptional)
- Reduces variance in inter-rater reliability; correlates strongly with objective outcomes

### VectorMemory Semantic Search

Semantic retrieval (top_k sampling from vector DB) is standard in:
- Retrieval-Augmented Generation (RAG): Langchain, LlamaIndex patterns
- Information retrieval: Elasticsearch, Pinecone, Weaviate standard practice
- LLM context optimization: Anthropic Prompt Caching, OpenAI function calling, Anthropic batch API all use semantic filtering

### Token Tracking & Budget Gates

Token counting + cost gating patterns exist in:
- OpenAI API SDKs (Python, JS): usage tracking in response objects
- Anthropic API: message.usage (input_tokens, output_tokens) in response
- AWS Lambda: cost estimation per invocation; budgets halt execution
- GCP BigQuery: costs/queries tracked; quotas enforced
- Production LLM systems: invariant that cost_used ≤ max_budget at mission end

### Session Caching

Session management for stateful agents is standard in:
- OpenAI Assistants API: explicit session_id parameter
- Anthropic Workbench: session context reuse across messages
- Production chatbots: session KV stores (Redis, DynamoDB) to reduce context resets
- Performance: stateful sessions reduce 20–30% of redundant context re-establishment

---

**Document generated:** 2026-04-09
**Plan reference:** /Users/eduardo/.claude/plans/memoized-gathering-kay.md
**Analysis reference:** /Users/eduardo/Projects/agentforce/docs/ANALYSIS_2026_04_09.md
