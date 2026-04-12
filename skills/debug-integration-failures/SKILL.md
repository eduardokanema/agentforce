---
name: debug-integration-failures
description: Debug AgentForce integration and system failures with a repro-first workflow grounded in real artifacts, persisted draft or run state, runtime routes, provider output parsing, and retry or replay paths. Use when unit tests alone are not enough and Codex needs to inspect real IDs and logs, add a deterministic repro script, prove a focused test red, apply a narrow seam fix, and verify the real integration path or a temp-copy replay fallback without over-claiming success.
---

# Debug Integration Failures

Use this repo-owned skill by explicit path until a separate discovery flow exists, for example: `Use $debug-integration-failures at skills/debug-integration-failures to ...`

Debug from real evidence first. Treat repro scripts, focused failing tests, and explicit verification gaps as the core output, not optional polish.

## Core Rules

- Inspect real artifacts, IDs, persisted state, route handlers, and exact error text before editing code.
- Choose the smallest executable repro surface that can prove the bug. Prefer a focused unit test when it reaches the seam; add a repro script only when the seam depends on real state, runtime wiring, or provider-shaped output.
- Make repro scripts repo-root-aware and deterministic. Accept explicit IDs, fixture files, or copied state roots. Do not depend on hidden shell state.
- Prove red before green. Run the repro script or failing test before the fix, then rerun the same commands after the fix.
- Keep the code change at the true seam. Do not refactor broadly while debugging an integration failure.
- Separate environment blockers from code regressions. If sandbox, network, auth, or filesystem limits block live verification, say so plainly.
- Prefer the closest real integration path for final verification. Use replay only when the live path is blocked, too risky, or too expensive for the current turn.
- Report concrete evidence: commands, failing error text, test names, run IDs, draft IDs, and any residual verification gap.
- Do not dump raw draft payloads, provider prompts, or secrets into logs or summaries. Print redacted summaries only.
- Do not use this skill for a pure unit-level failure that can be fixed and verified without persisted state, live routes, or replay.

## Workflow

1. Ground the bug in actual evidence.
   Read the failing artifact, persisted draft or run record, stream log, route, and parser or runtime seam before proposing a fix.

2. Localize the seam.
   Identify the smallest place where the failure becomes deterministic: parser, route, store, retry orchestration, provider adapter, or state write path.

3. Build the smallest repro surface.
   Add a focused failing test first when it reaches the seam.
   Add a repo-root-aware repro script when the seam depends on copied persisted state, runtime orchestration, or provider-shaped output.

4. Prove red.
   Run the repro command and the focused test before editing code. If they do not fail for the expected reason, the reproduction is incomplete.

5. Apply the narrowest fix.
   Patch the actual seam, not the surrounding workflow.

6. Prove green.
   Rerun the same repro script and focused tests. Add one nearby regression check if the parser or route already has similar coverage.

7. Verify the integration path.
   Prefer the real retry or runtime path.
   If that is blocked, replay against temp-copied real artifacts with the minimum necessary stubbing and state the exact gap between replay and live verification.

8. Report the outcome.
   Include the commands you ran, the red result, the green result, the live or replay verification result, and any remaining uncertainty.

## Evidence And Escalation

- Escalate only when a required command must write outside the sandbox, needs a blocked network path, or must touch live state that cannot be copied safely.
- If live verification is blocked by policy or environment, do not claim the issue is fully closed. State what was replayed and what remained unverified.
- When replaying, prefer temp-copy-only behavior. Keep the real `~/.agentforce` state read-only.
- If the bug is in Plan Mode or persisted state orchestration, read [references/agentforce-plan-mode.md](references/agentforce-plan-mode.md).
- For the general decision tree and evidence format, read [references/workflow.md](references/workflow.md).

## Resources

- `references/workflow.md`
  Use for live-vs-replay decisions, repro design, evidence formatting, and blocker reporting.

- `references/agentforce-plan-mode.md`
  Use for AgentForce draft, plan-run, planner, critic, and retry-path failures backed by `~/.agentforce`.

- `scripts/replay_plan_run.py`
  Use when a Plan Mode retry path must be replayed against temp-copied state with optional planner or critic stubs and redacted JSON output.
