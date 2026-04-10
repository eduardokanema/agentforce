"""Autonomous mission driver — runs entirely inside one delegated session.

This module runs the entire mission autonomously inside a single delegate_task call.
It spawns subprocesses for each worker and reviewer task and manages the
state machine internally.

Usage:
    delegate_task(
        goal="Run mission autonomously",
        context="Run the mission using: python3 -m agentforce.autonomous <mission_id>",
        ...
    )
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import uuid

from agentforce.connectors import CONNECTORS
import time
from concurrent.futures import ThreadPoolExecutor, Future
from datetime import datetime, timezone
from pathlib import Path

_STREAMS_DIR = Path.home() / ".agentforce" / "streams"
_STATE_DIR = Path.home() / ".agentforce" / "state"


def _pause_file(mission_id: str) -> Path:
    return _STATE_DIR / f"{mission_id}.pause"


def is_paused(mission_id: str) -> bool:
    return _pause_file(mission_id).exists()


def pause_mission(mission_id: str) -> None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _pause_file(mission_id).touch()


def resume_mission(mission_id: str) -> None:
    pf = _pause_file(mission_id)
    if pf.exists():
        pf.unlink()


def check_inject_queue(mission_id: str, task_id: str) -> str | None:
    path = Path(f"~/.agentforce/state/{mission_id}/{task_id}.inject").expanduser()
    try:
        if not path.exists():
            return None

        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        message = data.get("message")
        timestamp = data.get("timestamp")
        if not isinstance(message, str) or not isinstance(timestamp, str):
            return None

        try:
            path.unlink()
        except OSError:
            pass
        return message
    except (OSError, json.JSONDecodeError, AttributeError, TypeError, ValueError):
        return None


def _stream_path(mission_id: str, task_id: str) -> Path:
    _STREAMS_DIR.mkdir(parents=True, exist_ok=True)
    return _STREAMS_DIR / f"{mission_id}_{task_id}.log"


def _ensure_pkg():
    """Make sure agentforce is importable in source, installed, and frozen modes."""
    if importlib.util.find_spec("agentforce.core.engine") is not None:
        return Path(__file__).resolve().parent.parent

    paths = ["/opt/data/projects/agentforce", os.path.expanduser("~/projects/agentforce")]
    for p in paths:
        p = Path(p)
        if (p / "agentforce" / "core" / "engine.py").exists():
            if str(p) not in sys.path:
                sys.path.insert(0, str(p))
            return p
    raise SystemExit("Cannot find agentforce package")


def _detect_agent() -> str:
    """Auto-detect which agent to use: opencode only."""
    from agentforce.connectors import opencode as _oc
    if _oc.available():
        return "opencode"
    raise SystemExit("No agent CLI found. Install 'opencode'.")


def _run_agent(
    prompt: str,
    workdir: str,
    timeout: int = 300,
    agent: str = "auto",
    model: str = None,
    stream_path: Path = None,
    variant: str = None,
    session_id: str = None,
) -> tuple[bool, str, str, str | None, object]:
    """Dispatch to the selected connector. Returns (success, output, error, session_id, token_event)."""
    if agent == "auto":
        agent = _detect_agent()
    connector = CONNECTORS.get(agent)
    if connector is None:
        raise ValueError(f"Unknown agent: {agent!r}. Available: {list(CONNECTORS)}")
    result = connector(prompt, workdir, timeout, model, stream_path, variant, session_id)
    if len(result) == 4:
        return (*result, None)
    return result


def _parse_reviewer_output(output: str) -> dict:
    """Extract JSON from reviewer output.

    Scans from the *end* of the output so that tool-call results containing
    JSON (e.g. package.json file contents) don't mask the final verdict.
    Uses raw_decode so trailing non-JSON lines (e.g. codex's
    '── turn complete ...' footer) don't break parsing.
    """
    _decoder = json.JSONDecoder()
    lines = output.split("\n")

    # Walk backwards: find the last line that opens a JSON object, then use
    # raw_decode from that position — it parses one JSON value and ignores
    # everything after it, so trailing lines don't cause a parse failure.
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().startswith("{"):
            candidate = "\n".join(lines[i:])
            brace_pos = candidate.index("{")
            try:
                data, _ = _decoder.raw_decode(candidate, brace_pos)
                if isinstance(data, dict) and "approved" in data:
                    return data
            except json.JSONDecodeError:
                pass

    # Try a ```json fenced block (last occurrence wins)
    if "```json" in output:
        try:
            block = output.rsplit("```json", 1)[1].split("```", 1)[0].strip()
            data = json.loads(block)
            if isinstance(data, dict) and "approved" in data:
                return data
        except (json.JSONDecodeError, IndexError):
            pass

    raise ValueError("Could not parse reviewer output: no valid JSON found")


_MIN_APPROVAL_SCORE = 8


def _enforce_review_thresholds(review: dict) -> dict:
    """Apply mandatory approval thresholds to a parsed reviewer dict.

    Returns a new dict with ``approved`` forced to False (and ``feedback`` /
    ``blocking_issues`` updated) when:
    - score < _MIN_APPROVAL_SCORE
    - criteria_results.security is anything other than "met"

    The original dict is not mutated.
    """
    approved = review.get("approved", False)
    if not approved:
        return review

    score = review.get("score", 0)
    criteria = review.get("criteria_results", {})
    security_status = str(criteria.get("security", "met")).lower()

    if score < _MIN_APPROVAL_SCORE:
        return {
            **review,
            "approved": False,
            "feedback": f"[Score {score}/10 below threshold {_MIN_APPROVAL_SCORE}] {review.get('feedback', '')}",
        }

    if security_status != "met":
        return {
            **review,
            "approved": False,
            "blocking_issues": list(review.get("blocking_issues", [])) + [f"security: {security_status}"],
            "feedback": f"[Security issue: {security_status}] {review.get('feedback', '')}",
        }

    return review


HARD_BLOCK_THRESHOLD = 7  # scores strictly below this trigger immediate NEEDS_HUMAN


def _apply_hard_blocks(review: dict, task_state) -> bool:
    """Check per-criterion hard-block thresholds for Security and TDD.

    Mutates *task_state* in-place and returns True if a hard block was applied.
    Hard-blocked tasks go directly to NEEDS_HUMAN without consuming a retry slot.
    Missing score keys default to 10 to avoid false-positive blocks.
    """
    from agentforce.core.spec import TaskStatus

    scores = review.get("scores", {}) if isinstance(review.get("scores"), dict) else {}
    _raw_sec = scores.get("security", 10)
    _raw_tdd = scores.get("tdd", 10)
    security_score = _raw_sec if isinstance(_raw_sec, (int, float)) else 10
    tdd_score = _raw_tdd if isinstance(_raw_tdd, (int, float)) else 10

    if security_score < HARD_BLOCK_THRESHOLD:
        task_state.status = TaskStatus.NEEDS_HUMAN
        task_state.hard_block_reason = (
            f"HARD BLOCK: Security score {security_score}/10 below threshold "
            f"({HARD_BLOCK_THRESHOLD}). Fix security issues before retrying."
        )
        return True

    if tdd_score < HARD_BLOCK_THRESHOLD:
        task_state.status = TaskStatus.NEEDS_HUMAN
        task_state.hard_block_reason = (
            f"HARD BLOCK: TDD score {tdd_score}/10 below threshold "
            f"({HARD_BLOCK_THRESHOLD}). Tests must be defined before approval."
        )
        return True

    return False


_DEFAULT_MODEL = "opencode/nemotron-3-super-free"
_DEFAULT_VARIANT = "high"


def _get_or_create_session_id(session_ids: dict, tid: str, role: str) -> str | None:
    """Return (and if necessary create) a session_id for the given task and role.

    Workers: return None on first call so the agent creates a fresh session;
             return the stored session_id on subsequent calls.
    Reviewers: also return None on first call, then reuse the connector-returned
               session/thread id on subsequent review passes when available.
    """
    if role == "worker":
        return session_ids.get(tid)

    key = f"{tid}_reviewer"
    return session_ids.get(key)


def _record_usage(ledger, task_id: str, output: str) -> None:
    """Scan every line of agent output for usage JSON and accumulate in ledger."""
    from agentforce.core.token_ledger import TokenLedger
    for line in output.splitlines():
        usage = TokenLedger.parse_usage_line(line)
        if usage:
            ledger.add(task_id, usage["input_tokens"], usage["output_tokens"], usage["cost_usd"])


def run_autonomous(
    mission_id: str,
    workdir: str = None,
    agent: str = "auto",
    model: str = None,
    variant: str = None,
    pool_size: int = 8,
    extend_caps: bool = False,
    max_ticks: int = 2000,
):
    """Run a mission autonomously with a parallel supervisor loop.

    The supervisor ticks on a short interval, dispatches every available
    action (workers *and* reviewers) as concurrent threads, collects results
    as they finish, and feeds them back to the engine — all without blocking.
    """
    _ensure_pkg()
    from agentforce.core.engine import MissionEngine
    from agentforce.core.spec import ExecutionConfig, ExecutionProfile, TaskSpec
    from agentforce.core.token_ledger import TokenLedger
    from agentforce.memory import Memory
    from agentforce.telemetry import TelemetryStore, TaskMetrics, MissionMetrics

    state_file = Path.home() / ".agentforce" / "state" / f"{mission_id}.json"
    if not state_file.exists():
        print(f"No mission state found: {mission_id}")
        sys.exit(1)

    from agentforce.core.spec import TaskStatus

    memory = Memory(Path.home() / ".agentforce" / "memory")
    engine = MissionEngine.load(state_file, memory)
    persisted_defaults = engine.state.resolved_execution_defaults()

    def _resolve_role_default(role: str) -> ExecutionProfile:
        persisted = getattr(persisted_defaults, role)
        resolved_agent = (
            agent if agent != "auto"
            else (persisted.agent if persisted and persisted.agent else None)
        )
        if resolved_agent is None:
            resolved_agent = _detect_agent()
        return ExecutionProfile(
            agent=resolved_agent,
            model=model or (persisted.model if persisted and persisted.model else _DEFAULT_MODEL),
            thinking=variant or (persisted.thinking if persisted and persisted.thinking else _DEFAULT_VARIANT),
        )

    worker_runtime = _resolve_role_default("worker")
    reviewer_runtime = _resolve_role_default("reviewer")

    engine.state.execution_defaults = ExecutionConfig(
        worker=engine.spec.resolve_execution_profile(
            TaskSpec(id="__defaults__", title="", description=""),
            "worker",
            mission_defaults=engine.state.execution_defaults,
            runtime_fallback=worker_runtime,
        ),
        reviewer=engine.spec.resolve_execution_profile(
            TaskSpec(id="__defaults__", title="", description=""),
            "reviewer",
            mission_defaults=engine.state.execution_defaults,
            runtime_fallback=reviewer_runtime,
        ),
    )
    engine._sync_execution_telemetry()
    engine.state.caps_hit = {}

    resolved_agent = worker_runtime.agent
    eff_model = worker_runtime.model
    eff_variant = worker_runtime.thinking

    if extend_caps:
        # Raise all caps well above current counters so none trigger this run.
        # The stored mission state (counters, started_at) is not modified.
        c = engine.state.caps
        c.max_wall_time_minutes = 0          # 0 = disabled in wall_time_exceeded()
        c.max_retries_global = max(c.max_retries_global, engine.state.total_retries + 100)
        c.max_human_interventions = max(c.max_human_interventions, engine.state.total_human_interventions + 100)
        print("  ⟳ Caps ignored for this run (wall-time disabled, retry/intervention limits raised).")

    # On every resume: reset tasks that were interrupted or exhausted so they
    # can make progress again. IN_PROGRESS tasks belong to a dead process.
    # FAILED tasks get a fresh attempt (retries reset) so re-running the CLI is
    # enough to retry without manual intervention.
    _reset = False
    for ts in engine.state.task_states.values():
        if ts.status == TaskStatus.IN_PROGRESS:
            ts.status = TaskStatus.RETRY if ts.retries > 0 else TaskStatus.PENDING
            ts.bump()
            engine.state.log_event("task_reset", ts.task_id, "Interrupted IN_PROGRESS task reset on resume")
            _reset = True
        elif ts.status == TaskStatus.REVIEWING:
            # Reviewer was in-flight when the process died — re-queue for review.
            ts.status = TaskStatus.COMPLETED
            ts.review_feedback = ""
            ts.bump()
            engine.state.log_event("task_reset", ts.task_id, "Interrupted REVIEWING task reset on resume")
            _reset = True
        elif ts.status == TaskStatus.FAILED and not ts.human_intervention_needed:
            ts.retries = 0
            ts.status = TaskStatus.PENDING
            ts.error_message = ""
            ts.bump()
            engine.state.log_event("task_reset", ts.task_id, "FAILED task reset for re-run")
            _reset = True
    if _reset:
        engine.state.total_retries = 0

    engine._save()
    tele_store = TelemetryStore()
    start = datetime.now(timezone.utc)

    eff_pool = max(pool_size, engine.state.caps.max_concurrent_workers * 2 + 2)
    print(f"\n=== Autonomous Mission Runner ===")
    print(f"Mission : {engine.spec.name} [{engine.state.mission_id}]")
    print(f"Tasks   : {len(engine.spec.tasks)}")
    print(f"Agent   : {resolved_agent}  model={eff_model}  variant={eff_variant}")
    print(f"Workers : up to {engine.state.caps.max_concurrent_workers} concurrent  (thread pool: {eff_pool})")
    print(f"Workdir : {workdir or engine.state.working_dir}")
    print()

    ledger = TokenLedger()
    # Pre-seed from persisted task costs so cross-session totals accumulate correctly
    for _ts in engine.state.task_states.values():
        if _ts.tokens_in or _ts.tokens_out or _ts.cost_usd:
            ledger.add(_ts.task_id, _ts.tokens_in, _ts.tokens_out, _ts.cost_usd)

    task_metrics: dict[str, TaskMetrics] = {}
    # in_flight maps "task_id.role" → (Future, action)
    in_flight: dict[str, tuple[Future, object]] = {}
    # session_ids maps task_id → opencode session ID for caching across retries
    session_ids: dict[str, str] = {}

    _wdir = workdir or engine.state.working_dir

    def _submit(action) -> None:
        """Submit an action to the thread pool (non-blocking)."""
        key = f"{action.task_id}.{action.role}"
        if key in in_flight:
            return
        role = action.role
        tid = action.task_id
        timeout = getattr(action, "timeout", 300 if role == "worker" else 120)
        effective_agent = getattr(action, "agent", None) or resolved_agent
        effective_model = getattr(action, "model", None) or eff_model
        effective_variant = getattr(action, "thinking", None) or eff_variant

        # Reuse session for the same task across retries (enables caching)
        session_id = _get_or_create_session_id(session_ids, tid, role)

        sp = _stream_path(engine.state.mission_id, tid)
        if role == "worker":
            sp.write_text(f"=== WORKER [{tid}] STARTED ===\n", encoding="utf-8")
            task_metrics.setdefault(tid, TaskMetrics(
                task_id=tid,
                task_title=engine._get_task_spec(tid).title,
                mission_id=engine.state.mission_id,
                worker_started=datetime.now(timezone.utc).isoformat(),
            ))
            task_metrics[tid].worker_attempts += 1
        elif role == "reviewer":
            with open(sp, "a", encoding="utf-8") as _sf:
                _sf.write(f"\n=== REVIEWER [{tid}] STARTED ===\n")
            task_metrics.setdefault(tid, TaskMetrics(
                task_id=tid,
                task_title=engine._get_task_spec(tid).title,
                mission_id=engine.state.mission_id,
            ))
            task_metrics[tid].reviewer_started = datetime.now(timezone.utc).isoformat()
            task_metrics[tid].review_attempts += 1

        inject_message = check_inject_queue(engine.state.mission_id, tid)
        if inject_message:
            injected_line = f"[USER INSTRUCTION] {inject_message}"
            print(injected_line)
            with open(sp, "a", encoding="utf-8") as _sf:
                _sf.write(injected_line + "\n")
                _sf.flush()
            action.context = f"{injected_line}\n\n{action.context}"

        fut = executor.submit(
            _run_agent, action.context, _wdir, timeout,
            effective_agent, effective_model, sp, effective_variant, session_id,
        )
        in_flight[key] = (fut, action)
        print(f"  ↑ [{role}] task {tid} dispatched")

    def _collect() -> None:
        """Harvest any completed futures and apply results to the engine."""
        done_keys = [k for k, (f, _) in in_flight.items() if f.done()]
        for key in done_keys:
            fut, action = in_flight.pop(key)
            role = action.role
            tid = action.task_id

            try:
                success, output, error, returned_sid, token_event = fut.result()
            except Exception as exc:
                from agentforce.core.token_event import TokenEvent
                success, output, error, returned_sid, token_event = False, "", str(exc), None, TokenEvent(0, 0, 0.0)

            # Store returned connector session/thread IDs for reuse on retries.
            if returned_sid:
                if role == "worker" and tid not in session_ids:
                    session_ids[tid] = returned_sid
                elif role == "reviewer" and f"{tid}_reviewer" not in session_ids:
                    session_ids[f"{tid}_reviewer"] = returned_sid

            if role == "worker":
                now = datetime.now(timezone.utc).isoformat()
                tm = task_metrics.get(tid)
                if tm and tm.worker_started:
                    tm.worker_finished = now
                    tm.worker_duration_s = (
                        datetime.fromisoformat(now) - datetime.fromisoformat(tm.worker_started)
                    ).total_seconds()
                print(f"  ↓ [worker] task {tid}  success={success}  output={len(output)}B")
                if error and "timed out" in error:
                    print(f"    timed out — retrying without consuming a retry slot")
                    ts = engine.state.get_task(tid)
                    if ts:
                        ts.status = TaskStatus.RETRY
                    engine._save()
                    continue
                if error:
                    print(f"    error: {error[:200]}")
                _record_usage(ledger, tid, output)
                if token_event is not None:
                    ledger.add(tid, token_event.tokens_in, token_event.tokens_out, token_event.cost_usd)
                ts = engine.state.get_task(tid)
                if ts:
                    t = ledger.task_totals(tid)
                    # Compute per-attempt delta before overwriting cumulative totals
                    attempt_tokens_in = t["tokens_in"] - (ts.tokens_in or 0)
                    attempt_tokens_out = t["tokens_out"] - (ts.tokens_out or 0)
                    attempt_cost_usd = t["cost_usd"] - (ts.cost_usd or 0.0)
                    ts.tokens_in = t["tokens_in"]
                    ts.tokens_out = t["tokens_out"]
                    ts.cost_usd = t["cost_usd"]
                    if success:
                        ts.attempt_history.append({
                            "attempt_number": len(ts.attempt_history) + 1,
                            "output": output,
                            "tokens_in": attempt_tokens_in,
                            "tokens_out": attempt_tokens_out,
                            "cost_usd": round(attempt_cost_usd, 6),
                        })
                mt = ledger.mission_totals()
                engine.state.tokens_in = mt["tokens_in"]
                engine.state.tokens_out = mt["tokens_out"]
                engine.state.cost_usd = mt["cost_usd"]
                engine.apply_worker_result(tid, success, output, error)
                engine._save()

            elif role == "reviewer":
                now = datetime.now(timezone.utc).isoformat()
                tm = task_metrics.get(tid)
                if tm and tm.reviewer_started:
                    tm.reviewer_finished = now
                    tm.reviewer_duration_s = (
                        datetime.fromisoformat(now) - datetime.fromisoformat(tm.reviewer_started)
                    ).total_seconds()

                if not success and error and "timed out" in error:
                    print(f"  ↓ [reviewer] task {tid}  timed out — re-dispatching reviewer")
                    ts = engine.state.get_task(tid)
                    if ts:
                        ts.status = TaskStatus.COMPLETED  # triggers reviewer re-dispatch
                    engine._save()
                    continue

                if not success and error and ("no rollout found" in error or "thread/resume" in error):
                    print(f"  ↓ [reviewer] task {tid}  session expired — clearing session and re-dispatching reviewer")
                    session_ids.pop(f"{tid}_reviewer", None)  # force a fresh session next dispatch
                    ts = engine.state.get_task(tid)
                    if ts:
                        ts.status = TaskStatus.COMPLETED  # triggers reviewer re-dispatch
                    engine._save()
                    continue

                if success and output:
                    try:
                        review = _parse_reviewer_output(output)
                    except ValueError as exc:
                        msg = str(exc)
                        print(f"  [CRITICAL] task {tid}: {msg}")
                        print(f"    Reviewer produced unreadable output — marking task as permanently failed.")
                        task_spec = engine._get_task_spec(tid)
                        ts = engine.state.get_task(tid)
                        if ts and task_spec:
                            ts.retries = task_spec.max_retries  # exhaust retries
                        engine.apply_reviewer_result(tid, False, msg, 0, [])
                        engine._save()
                        continue
                else:
                    review = {"approved": False, "feedback": f"Reviewer error: {error}", "score": 0}

                review = _enforce_review_thresholds(review)
                approved = review.get("approved", False)
                score = review.get("score", 0)
                feedback = review.get("feedback", "")
                blocking = review.get("blocking_issues", [])

                if tm:
                    tm.review_score = score
                    tm.review_approved = approved
                    tm.review_issues_count = len(blocking)

                # Hard-block check: Security/TDD below threshold → NEEDS_HUMAN immediately
                ts = engine.state.get_task(tid)
                if ts and _apply_hard_blocks(review, ts):
                    print(f"  ↓ [reviewer] task {tid}  HARD BLOCK: {ts.hard_block_reason}")
                    engine.state.log_event("hard_block", tid, ts.hard_block_reason)
                    _record_usage(ledger, tid, output if success else "")
                    if ts:
                        t = ledger.task_totals(tid)
                        reviewer_cost_delta = t["cost_usd"] - (ts.cost_usd or 0.0)
                        reviewer_tokens_in_delta = t["tokens_in"] - (ts.tokens_in or 0)
                        reviewer_tokens_out_delta = t["tokens_out"] - (ts.tokens_out or 0)
                        ts.tokens_in = t["tokens_in"]
                        ts.tokens_out = t["tokens_out"]
                        ts.cost_usd = t["cost_usd"]
                        if ts.attempt_history:
                            last = ts.attempt_history[-1]
                            last["review"] = ts.hard_block_reason
                            last["score"] = 0
                            last["tokens_in"] = last.get("tokens_in", 0) + reviewer_tokens_in_delta
                            last["tokens_out"] = last.get("tokens_out", 0) + reviewer_tokens_out_delta
                            last["cost_usd"] = round(last.get("cost_usd", 0.0) + reviewer_cost_delta, 6)
                    mt = ledger.mission_totals()
                    engine.state.tokens_in = mt["tokens_in"]
                    engine.state.tokens_out = mt["tokens_out"]
                    engine.state.cost_usd = mt["cost_usd"]
                    engine._save()
                    continue

                print(f"  ↓ [reviewer] task {tid}  approved={approved}  score={score}")
                if not approved and feedback:
                    print(f"    feedback: {feedback[:200]}")
                _record_usage(ledger, tid, output if success else "")
                if ts:
                    t = ledger.task_totals(tid)
                    # Add reviewer cost delta to the last attempt entry
                    reviewer_cost_delta = t["cost_usd"] - (ts.cost_usd or 0.0)
                    reviewer_tokens_in_delta = t["tokens_in"] - (ts.tokens_in or 0)
                    reviewer_tokens_out_delta = t["tokens_out"] - (ts.tokens_out or 0)
                    ts.tokens_in = t["tokens_in"]
                    ts.tokens_out = t["tokens_out"]
                    ts.cost_usd = t["cost_usd"]
                    if ts.attempt_history:
                        last = ts.attempt_history[-1]
                        last["review"] = feedback
                        last["score"] = score
                        last["tokens_in"] = last.get("tokens_in", 0) + reviewer_tokens_in_delta
                        last["tokens_out"] = last.get("tokens_out", 0) + reviewer_tokens_out_delta
                        last["cost_usd"] = round(last.get("cost_usd", 0.0) + reviewer_cost_delta, 6)
                mt = ledger.mission_totals()
                engine.state.tokens_in = mt["tokens_in"]
                engine.state.tokens_out = mt["tokens_out"]
                engine.state.cost_usd = mt["cost_usd"]
                engine.apply_reviewer_result(tid, approved, feedback, score, blocking)
                engine._save()

    tick = 0
    idle_ticks = 0

    with ThreadPoolExecutor(max_workers=eff_pool) as executor:
        while tick < max_ticks:
            tick += 1

            # Collect finished work first (non-blocking)
            _collect()

            # Terminal conditions
            if engine.is_done() and not in_flight:
                print(f"\n✓ Mission complete! ({tick} ticks)")
                break
            if engine.is_failed() and not in_flight:
                if "budget" in engine.state.caps_hit:
                    total_cost = sum(ts.cost_usd for ts in engine.state.task_states.values())
                    cap = engine.state.caps.max_cost_usd
                    print(f"\nBudget cap exceeded: ${total_cost:.4f} >= max_cost_usd=${cap:.2f}. Halting.")
                else:
                    print(f"\n✗ Mission failed. ({tick} ticks)")
                break

            # Get new actions from the engine
            actions = engine.tick()

            for action in actions:
                role = getattr(action, "role", "")
                if role in ("worker", "reviewer") and hasattr(action, "context"):
                    _submit(action)
                elif hasattr(action, "message"):  # HumanIntervention
                    print(f"  ⚠ Human intervention [{action.task_id}]: {getattr(action, 'message', '')[:120]}")
                    print(f"    Auto-resolving with reviewer context.")
                    engine.apply_human_resolution(
                        action.task_id, getattr(action, "message", "Fix the blocking issues listed above.")
                    )
                    engine._save()

            if not actions and not in_flight:
                idle_ticks += 1
                if idle_ticks >= 3:
                    print(f"\n  No actions and nothing in flight — stopping.")
                    break
            else:
                idle_ticks = 0

            # Print after _submit so newly dispatched tasks are counted
            active = len(in_flight)
            if tick % 5 == 0 and active:
                print(f"  [tick {tick}] {active} agent(s) running: {list(in_flight)}")

            # Pause support: block here while pause file exists
            if is_paused(engine.state.mission_id):
                print(f"  ⏸  Mission paused. Remove pause file or run: mission resume {engine.state.mission_id}")
                while is_paused(engine.state.mission_id):
                    time.sleep(2)
                print(f"  ▶  Mission resumed.")

            time.sleep(2)  # supervisor poll interval

    # Warn if we exited only because the tick limit was reached
    if tick >= max_ticks and not engine.is_done() and not engine.is_failed():
        approved = sum(1 for ts in engine.state.task_states.values() if ts.status == "approved")
        total = len(engine.spec.tasks)
        print(
            f"\n⚠  Tick limit ({max_ticks}) reached — mission is NOT complete.\n"
            f"   Completed {approved}/{total} tasks.\n"
            f"   Resume with:\n"
            f"     python3 -m agentforce.autonomous {mission_id}\n"
            f"   Or raise the limit:\n"
            f"     python3 -m agentforce.autonomous --max-ticks {max_ticks * 2} {mission_id}\n"
        )

    # Build final metrics
    end = datetime.now(timezone.utc)
    mission_metrics = MissionMetrics(
        mission_id=engine.state.mission_id,
        mission_name=engine.spec.name,
        started_at=engine.state.started_at,
        completed_at=end.isoformat(),
        total_duration_s=(end - datetime.fromisoformat(engine.state.started_at)).total_seconds(),
        total_tasks=len(engine.spec.tasks),
        approved_on_first_try=sum(
            1 for tm in task_metrics.values()
            if tm.review_approved and tm.retries == 0
        ),
        approved_with_retries=sum(
            1 for tm in task_metrics.values()
            if tm.review_approved and tm.retries > 0
        ),
        failed=sum(
            1 for ts in engine.state.task_states.values()
            if ts.status == "failed"
        ),
        total_retries=engine.state.total_retries,
        total_human_interventions=engine.state.total_human_interventions,
        worker_tasks=sum(tm.worker_attempts for tm in task_metrics.values()),
        reviewer_tasks=sum(tm.review_attempts for tm in task_metrics.values()),
        task_metrics={k: v.to_dict() for k, v in task_metrics.items()},
    )

    scores = [tm.review_score for tm in task_metrics.values() if tm.review_score > 0]
    if scores:
        mission_metrics.avg_review_score = sum(scores) / len(scores)
        mission_metrics.min_review_score = min(scores)
        mission_metrics.max_review_score = max(scores)

    tele_store.save_mission(mission_metrics)

    report = engine.report()
    print(f"\n{'=' * 60}")
    print(report)
    print(f"{'=' * 60}")
    print(f"\nMission metrics saved to: {tele_store.get_mission_file(engine.state.mission_id)}")
    print(f"State saved to: {engine.state_file}")

    return engine.state.is_done()


if __name__ == "__main__":
    import argparse as _ap

    p = _ap.ArgumentParser(
        prog="python3 -m agentforce.autonomous",
        description="Run an AgentForce mission autonomously.",
    )
    p.add_argument("mission_id", help="Mission ID to run")
    p.add_argument("--workdir", help="Override working directory")
    p.add_argument(
        "--agent",
        default="auto",
        choices=["auto", *CONNECTORS],
        help="Agent CLI to use (default: auto — opencode)",
    )
    p.add_argument(
        "--model",
        default=None,
        help=f"Model to pass to the agent CLI (default: {_DEFAULT_MODEL})",
    )
    p.add_argument(
        "--variant",
        default=None,
        help=f"Reasoning effort variant (default: {_DEFAULT_VARIANT})",
    )
    p.add_argument(
        "--pool-size",
        type=int,
        default=8,
        metavar="N",
        help="Max concurrent agent threads (default: 8). Actual task parallelism is "
             "also governed by the mission's max_concurrent_workers cap.",
    )
    p.add_argument(
        "--extend-caps",
        action="store_true",
        default=False,
        help="Ignore cap limits for this run: disables wall-time and raises "
             "retry/intervention limits above current counters. Use when resuming "
             "a mission blocked by wall_time, interventions, or retry limits.",
    )
    p.add_argument(
        "--max-ticks",
        type=int,
        default=2000,
        metavar="N",
        help="Maximum supervisor loop ticks before stopping (default: 2000). "
             "Increase for long-running missions.",
    )
    a = p.parse_args()

    success = run_autonomous(
        a.mission_id, a.workdir,
        agent=a.agent, model=a.model, variant=a.variant, pool_size=a.pool_size,
        extend_caps=a.extend_caps, max_ticks=a.max_ticks,
    )
    sys.exit(0 if success else 1)
