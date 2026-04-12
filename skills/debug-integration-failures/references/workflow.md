# Integration Debug Workflow

Use this reference when the failure crosses parser, route, store, runtime, or persisted-state boundaries.

## Decide Between Live Verification And Replay

Use live verification when:
- the real route or CLI can run safely in the current environment
- the failure depends on real wiring that a replay would hide
- the required state can be exercised without mutating production or operator-owned artifacts

Use replay when:
- the live provider path is blocked by sandbox, policy, auth, or cost
- the live server is unavailable but the persisted artifacts and orchestration code are present
- you need to isolate one seam, such as parser output handling or retry-path bookkeeping, without re-running the full system

Do not use replay as a shortcut when the real path is available and safe.

## Choose The Smallest Repro Surface

Prefer, in order:
1. a focused unit test if it reaches the seam
2. a small repro script if the seam needs copied state or runtime orchestration
3. a full route or CLI run only when the smaller surfaces miss the bug

Use a repro script only when it adds determinism or reaches a seam that tests alone cannot cover.

## Keep Repros Deterministic

- Accept explicit IDs, file paths, or fixture files
- Add repo-root-aware imports for scripts stored outside the main package tree
- Copy live artifacts into temp state before replaying
- Stub only the part that is truly external or blocked
- Keep raw outputs in files or fixtures, not hardcoded deep in the script body unless the payload is tiny

If the repro passes before the fix, the reproduction is incomplete.

## Prove Red Then Green

Capture:
- the exact red command
- the failing error text or assertion
- the exact green command
- the passing test name or replay summary

Good command shapes:
- `python3 scripts/repro_*.py`
- `python3 -m pytest -q tests/... -k ...`
- a replay helper that prints a JSON summary with run status and step statuses

## Report Environment Blockers Cleanly

Separate these from regressions:
- sandboxed filesystem writes
- blocked network or external provider policy
- missing local server or daemon process
- missing auth or model access

If the blocker prevents live verification, say:
- what command was blocked
- why it was blocked
- what replay or adjacent verification you used instead
- what remains unverified

## Do Not Write A Replay Script When

- a focused test already reaches the seam directly
- the issue is purely local parsing or data transformation with no runtime wiring
- the replay script would contain more logic than the bug fix itself

## Evidence Template

Include these fields in the final report when applicable:
- failing artifact IDs
- parser or route seam
- repro command
- red result
- focused fix summary
- green result
- live verification result or replay result
- residual gap
