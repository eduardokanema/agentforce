# AgentForce Plan Mode Debug Notes

Use this reference when the failure involves planner synthesis, critic passes, resolver repair, persisted drafts, or plan-run retry behavior.

## Main Seams

- `agentforce/server/planner_adapter.py`
  Use for provider completion parsing, planner output normalization, and mixed-output extraction bugs.

- `agentforce/server/planning_runtime.py`
  Use for plan-run orchestration, critic execution, resolver flow, repair gating, and replay-path verification.

- `agentforce/server/routes/plan.py`
  Use for draft creation, retry enqueueing, preflight gating, and route-level trigger behavior.

## Persisted Artifacts

- Drafts live under `~/.agentforce/drafts/<draft-id>.json`
- Plan runs live under `~/.agentforce/plans/runs/<run-id>.json`
- Plan versions live under `~/.agentforce/plans/versions/<version-id>.json`

Read the real draft and failing run first. Use the persisted `error_message`, `current_step`, and step list to localize where the run failed before touching code.

## Replay Guidance

Use `scripts/replay_plan_run.py` when:
- the live server is not running
- provider execution is blocked
- you need to validate retry-path bookkeeping or parser behavior against copied real artifacts

Replay rules:
- keep the real state root read-only
- copy only the referenced draft and run artifacts into temp state
- stub planner output only when the provider path is external or blocked
- stub critic output or mission-plan validation only when isolating a narrower seam
- print only redacted JSON summaries, not raw prompts or full draft payloads

## Worked Example

Recent incident:
- draft id: `6316696a-8d66-467c-b7b8-6ddd418e86e6`
- failing run id: `b65e5dbc-5e5f-4ead-a2e1-6da47d73ac9f`
- failing step: `planner_synthesis`
- error: `planner response missing assistant_message`

What mattered:
- the planner sometimes returned a bare MissionSpec JSON object instead of `{assistant_message, draft_spec}`
- nested JSON extraction could accidentally grab the inner `caps: {}` object instead of the outer mission spec
- a focused parser test plus a tiny repro script proved the failure red
- a temp-copy replay validated the retry path after the parser fix when live Codex execution was blocked

## Useful Command Shapes

- inspect persisted artifacts:
  `sed -n '1,220p' ~/.agentforce/drafts/<draft-id>.json`
  `sed -n '1,220p' ~/.agentforce/plans/runs/<run-id>.json`

- run the parser-focused repro:
  `python3 scripts/repro_*.py`

- run the focused regression:
  `python3 -m pytest -q tests/...`

- replay the retry path on copied state:
  `python3 skills/debug-integration-failures/scripts/replay_plan_run.py --draft-id <draft-id> --source-run-id <run-id> --planner-output-file /tmp/planner.txt --critic-output-file /tmp/critic.json --stub-empty-validation`
