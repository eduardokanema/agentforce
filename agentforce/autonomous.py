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

from agentforce.core.engine import detect_runtime_agent, normalize_runtime_profile

def _agentforce_home() -> Path:
    return Path.home() / ".agentforce"


def _pause_file(mission_id: str) -> Path:
    return _agentforce_home() / "state" / f"{mission_id}.pause"


def is_paused(mission_id: str) -> bool:
    return _pause_file(mission_id).exists()


def pause_mission(mission_id: str) -> None:
    (_agentforce_home() / "state").mkdir(parents=True, exist_ok=True)
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
    streams_dir = _agentforce_home() / "streams"
    streams_dir.mkdir(parents=True, exist_ok=True)
    return streams_dir / f"{mission_id}_{task_id}.log"


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
    """Auto-detect which agent to use: gemini > claude > opencode."""
    return detect_runtime_agent()


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


def _next_retry_delay_seconds(engine) -> float | None:
    """Return the shortest remaining retry backoff, if any."""
    from agentforce.core.spec import TaskStatus

    now = time.time()
    remaining_delays: list[float] = []
    for task_state in engine.state.task_states.values():
        if task_state.status != TaskStatus.RETRY or not task_state.retry_not_before:
            continue
        remaining = task_state.retry_not_before - now
        if remaining > 0:
            remaining_delays.append(remaining)

    if not remaining_delays:
        return None
    return min(remaining_delays)


def _status_value(status) -> str:
    return getattr(status, "value", status)


def _task_retry_count(task_state) -> int:
    lifetime_retries = getattr(task_state, "lifetime_retries", 0)
    if isinstance(lifetime_retries, int) and lifetime_retries > 0:
        return lifetime_retries
    retries = getattr(task_state, "retries", 0)
    return retries if isinstance(retries, int) else 0


def _resolve_role_default(persisted_defaults, role: str, agent: str, model: str | None, variant: str | None):
    persisted = getattr(persisted_defaults, role)
    resolved_agent = (
        agent if agent != "auto"
        else (persisted.agent if persisted and persisted.agent else None)
    )
    if resolved_agent is None:
        resolved_agent = _detect_agent()
    return normalize_runtime_profile(
        agent=resolved_agent,
        model=model or (persisted.model if persisted and persisted.model else None),
        thinking=variant or (persisted.thinking if persisted and persisted.thinking else _DEFAULT_VARIANT),
    )


def _resolve_execution_defaults(engine, agent: str, model: str | None, variant: str | None):
    from agentforce.core.spec import ExecutionConfig

    persisted_defaults = engine.state.resolved_execution_defaults()
    worker_runtime = _resolve_role_default(persisted_defaults, "worker", agent, model, variant)
    reviewer_runtime = _resolve_role_default(persisted_defaults, "reviewer", agent, model, variant)
    engine.state.execution_defaults = ExecutionConfig(
        worker=worker_runtime,
        reviewer=reviewer_runtime,
    )
    engine._sync_execution_telemetry()
    engine.state.caps_hit = {}
    return worker_runtime, reviewer_runtime


def _apply_extend_caps(engine) -> None:
    # Raise all caps well above current counters so none trigger this run.
    # The stored mission state (counters, started_at) is not modified.
    caps = engine.state.caps
    caps.max_wall_time_minutes = 0
    caps.max_retries_global = max(caps.max_retries_global, engine.state.total_retries + 100)
    caps.max_human_interventions = max(
        caps.max_human_interventions,
        engine.state.total_human_interventions + 100,
    )
    print("  ⟳ Caps ignored for this run (wall-time disabled, retry/intervention limits raised).")


def _reset_resumable_tasks(engine) -> None:
    from agentforce.core.spec import TaskStatus

    reset_any = False
    for task_state in engine.state.task_states.values():
        if task_state.status == TaskStatus.IN_PROGRESS:
            task_state.status = TaskStatus.RETRY if task_state.retries > 0 else TaskStatus.PENDING
            task_state.bump()
            engine.state.log_event(
                "task_reset",
                task_state.task_id,
                "Interrupted IN_PROGRESS task reset on resume",
            )
            reset_any = True
        elif task_state.status == TaskStatus.REVIEWING:
            task_state.status = TaskStatus.COMPLETED
            task_state.review_feedback = ""
            task_state.bump()
            engine.state.log_event(
                "task_reset",
                task_state.task_id,
                "Interrupted REVIEWING task reset on resume",
            )
            reset_any = True
        elif task_state.status == TaskStatus.FAILED and not task_state.human_intervention_needed:
            task_state.retries = 0
            task_state.status = TaskStatus.PENDING
            task_state.error_message = ""
            task_state.bump()
            engine.state.log_event(
                "task_reset",
                task_state.task_id,
                "FAILED task reset for re-run",
            )
            reset_any = True
    if reset_any:
        engine.state.total_retries = 0


def _print_startup_banner(engine, workdir: str, resolved_agent: str, model: str | None, variant: str | None, eff_pool: int) -> None:
    print(f"\n=== Autonomous Mission Runner ===")
    print(f"Mission : {engine.spec.name} [{engine.state.mission_id}]")
    print(f"Tasks   : {len(engine.spec.tasks)}")
    print(f"Agent   : {resolved_agent}  model={model}  variant={variant}")
    print(f"Workers : up to {engine.state.caps.max_concurrent_workers} concurrent  (thread pool: {eff_pool})")
    print(f"Workdir : {workdir}")
    print()


def _seed_ledger_from_state(ledger, task_states: dict) -> None:
    for task_state in task_states.values():
        if task_state.tokens_in or task_state.tokens_out or task_state.cost_usd:
            ledger.add(task_state.task_id, task_state.tokens_in, task_state.tokens_out, task_state.cost_usd)


def _count_review_approved_tasks(task_states: dict[str, object]) -> int:
    from agentforce.core.spec import TaskStatus

    return sum(
        1
        for task_state in task_states.values()
        if _status_value(task_state.status) == TaskStatus.REVIEW_APPROVED.value
    )


def _count_approved_tasks(task_states: dict[str, object]) -> tuple[int, int]:
    from agentforce.core.spec import TaskStatus

    approved_on_first_try = 0
    approved_with_retries = 0
    for task_state in task_states.values():
        if _status_value(task_state.status) != TaskStatus.REVIEW_APPROVED.value:
            continue
        if _task_retry_count(task_state) > 0:
            approved_with_retries += 1
        else:
            approved_on_first_try += 1
    return approved_on_first_try, approved_with_retries


def _build_mission_metrics(engine, task_metrics: dict[str, object], completed_at: str):
    from agentforce.core.spec import TaskStatus
    from agentforce.telemetry import MissionMetrics

    approved_on_first_try, approved_with_retries = _count_approved_tasks(engine.state.task_states)
    for task_id, task_metric in task_metrics.items():
        task_state = engine.state.get_task(task_id)
        if task_state:
            task_metric.retries = _task_retry_count(task_state)

    mission_metrics = MissionMetrics(
        mission_id=engine.state.mission_id,
        mission_name=engine.spec.name,
        started_at=engine.state.started_at,
        completed_at=completed_at,
        total_duration_s=engine.state.active_wall_time_seconds,
        total_tasks=len(engine.spec.tasks),
        approved_on_first_try=approved_on_first_try,
        approved_with_retries=approved_with_retries,
        failed=sum(
            1
            for task_state in engine.state.task_states.values()
            if _status_value(task_state.status) == TaskStatus.FAILED.value
        ),
        total_retries=engine.state.total_retries,
        total_human_interventions=engine.state.total_human_interventions,
        worker_tasks=sum(task_metric.worker_attempts for task_metric in task_metrics.values()),
        reviewer_tasks=sum(task_metric.review_attempts for task_metric in task_metrics.values()),
        task_metrics={task_id: task_metric.to_dict() for task_id, task_metric in task_metrics.items()},
    )

    scores = [task_metric.review_score for task_metric in task_metrics.values() if task_metric.review_score > 0]
    if scores:
        mission_metrics.avg_review_score = sum(scores) / len(scores)
        mission_metrics.min_review_score = min(scores)
        mission_metrics.max_review_score = max(scores)

    return mission_metrics


class _AutonomousRunner:
    def __init__(
        self,
        engine,
        workdir: str,
        resolved_agent: str,
        model: str | None,
        variant: str | None,
        eff_pool: int,
        ledger,
        task_metrics_cls,
        task_status_cls,
    ) -> None:
        self.engine = engine
        self.workdir = workdir
        self.resolved_agent = resolved_agent
        self.model = model
        self.variant = variant
        self.eff_pool = eff_pool
        self.ledger = ledger
        self.TaskMetrics = task_metrics_cls
        self.TaskStatus = task_status_cls
        self.task_metrics: dict[str, object] = {}
        self.in_flight: dict[str, tuple[Future, object]] = {}
        self.session_ids: dict[str, str] = {}
        self.tick = 0
        self.idle_ticks = 0
        self.executor: ThreadPoolExecutor | None = None

    def _set_task_metric_retries(self, task_id: str, task_state) -> None:
        task_metric = self.task_metrics.get(task_id)
        if task_metric and task_state:
            task_metric.retries = _task_retry_count(task_state)

    def _sync_mission_totals(self) -> None:
        totals = self.ledger.mission_totals()
        self.engine.state.tokens_in = totals["tokens_in"]
        self.engine.state.tokens_out = totals["tokens_out"]
        self.engine.state.cost_usd = totals["cost_usd"]

    def _apply_task_totals(self, task_id: str, task_state) -> tuple[int, int, float]:
        totals = self.ledger.task_totals(task_id)
        delta_tokens_in = totals["tokens_in"] - (task_state.tokens_in or 0)
        delta_tokens_out = totals["tokens_out"] - (task_state.tokens_out or 0)
        delta_cost_usd = totals["cost_usd"] - (task_state.cost_usd or 0.0)
        task_state.tokens_in = totals["tokens_in"]
        task_state.tokens_out = totals["tokens_out"]
        task_state.cost_usd = totals["cost_usd"]
        self._sync_mission_totals()
        self._set_task_metric_retries(task_id, task_state)
        return delta_tokens_in, delta_tokens_out, delta_cost_usd

    def _mark_worker_started(self, task_id: str) -> None:
        task_metric = self.task_metrics.setdefault(
            task_id,
            self.TaskMetrics(
                task_id=task_id,
                task_title=self.engine._get_task_spec(task_id).title,
                mission_id=self.engine.state.mission_id,
                worker_started=datetime.now(timezone.utc).isoformat(),
            ),
        )
        task_metric.worker_attempts += 1

    def _mark_reviewer_started(self, task_id: str) -> None:
        task_metric = self.task_metrics.setdefault(
            task_id,
            self.TaskMetrics(
                task_id=task_id,
                task_title=self.engine._get_task_spec(task_id).title,
                mission_id=self.engine.state.mission_id,
            ),
        )
        task_metric.reviewer_started = datetime.now(timezone.utc).isoformat()
        task_metric.review_attempts += 1

    def _submit(self, action) -> None:
        key = f"{action.task_id}.{action.role}"
        if key in self.in_flight:
            return

        role = action.role
        task_id = action.task_id
        timeout = getattr(action, "timeout", 300 if role == "worker" else 120)
        effective_agent = getattr(action, "agent", None) or self.resolved_agent
        effective_model = getattr(action, "model", None) or self.model
        effective_variant = getattr(action, "thinking", None) or self.variant
        session_id = _get_or_create_session_id(self.session_ids, task_id, role)

        stream_path = _stream_path(self.engine.state.mission_id, task_id)
        if role == "worker":
            stream_path.write_text(f"=== WORKER [{task_id}] STARTED ===\n", encoding="utf-8")
            self._mark_worker_started(task_id)
        elif role == "reviewer":
            with open(stream_path, "a", encoding="utf-8") as stream_file:
                stream_file.write(f"\n=== REVIEWER [{task_id}] STARTED ===\n")
            self._mark_reviewer_started(task_id)

        inject_message = check_inject_queue(self.engine.state.mission_id, task_id)
        if inject_message:
            injected_line = f"[USER INSTRUCTION] {inject_message}"
            print(injected_line)
            with open(stream_path, "a", encoding="utf-8") as stream_file:
                stream_file.write(injected_line + "\n")
                stream_file.flush()
            action.context = f"{injected_line}\n\n{action.context}"

        future = self.executor.submit(
            _run_agent,
            action.context,
            self.workdir,
            timeout,
            effective_agent,
            effective_model,
            stream_path,
            effective_variant,
            session_id,
        )
        self.in_flight[key] = (future, action)
        print(f"  ↑ [{role}] task {task_id} dispatched")

    def _handle_worker_completion(self, task_id: str, success: bool, output: str, error: str, token_event) -> None:
        now = datetime.now(timezone.utc).isoformat()
        task_metric = self.task_metrics.get(task_id)
        if task_metric and task_metric.worker_started:
            task_metric.worker_finished = now
            task_metric.worker_duration_s = (
                datetime.fromisoformat(now) - datetime.fromisoformat(task_metric.worker_started)
            ).total_seconds()

        print(f"  ↓ [worker] task {task_id}  success={success}  output={len(output)}B")
        if error and "timed out" in error:
            print(f"    timed out — retrying without consuming a retry slot")
            task_state = self.engine.state.get_task(task_id)
            if task_state:
                task_state.status = self.TaskStatus.RETRY
                if output:
                    task_state.timeout_output = output
                self._set_task_metric_retries(task_id, task_state)
            self.engine._save()
            return

        if error:
            print(f"    error: {error[:200]}")

        _record_usage(self.ledger, task_id, output)
        if token_event is not None:
            self.ledger.add(task_id, token_event.tokens_in, token_event.tokens_out, token_event.cost_usd)

        task_state = self.engine.state.get_task(task_id)
        if task_state:
            delta_tokens_in, delta_tokens_out, delta_cost_usd = self._apply_task_totals(task_id, task_state)
            if success:
                task_state.attempt_history.append({
                    "attempt_number": len(task_state.attempt_history) + 1,
                    "output": output,
                    "tokens_in": delta_tokens_in,
                    "tokens_out": delta_tokens_out,
                    "cost_usd": round(delta_cost_usd, 6),
                })

        self.engine.apply_worker_result(task_id, success, output, error)
        self._set_task_metric_retries(task_id, self.engine.state.get_task(task_id))
        self.engine._save()

    def _handle_reviewer_completion(self, task_id: str, success: bool, output: str, error: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        task_metric = self.task_metrics.get(task_id)
        if task_metric and task_metric.reviewer_started:
            task_metric.reviewer_finished = now
            task_metric.reviewer_duration_s = (
                datetime.fromisoformat(now) - datetime.fromisoformat(task_metric.reviewer_started)
            ).total_seconds()

        if not success and error and "timed out" in error:
            print(f"  ↓ [reviewer] task {task_id}  timed out — re-dispatching reviewer")
            task_state = self.engine.state.get_task(task_id)
            if task_state:
                task_state.status = self.TaskStatus.COMPLETED
                self._set_task_metric_retries(task_id, task_state)
            self.engine._save()
            return

        if not success and error and ("no rollout found" in error or "thread/resume" in error):
            print(f"  ↓ [reviewer] task {task_id}  session expired — clearing session and re-dispatching reviewer")
            self.session_ids.pop(f"{task_id}_reviewer", None)
            task_state = self.engine.state.get_task(task_id)
            if task_state:
                task_state.status = self.TaskStatus.COMPLETED
                self._set_task_metric_retries(task_id, task_state)
            self.engine._save()
            return

        if success and output:
            try:
                review = _parse_reviewer_output(output)
            except ValueError as exc:
                message = str(exc)
                print(f"  [CRITICAL] task {task_id}: {message}")
                print(f"    Reviewer produced unreadable output — marking task as permanently failed.")
                task_spec = self.engine._get_task_spec(task_id)
                task_state = self.engine.state.get_task(task_id)
                if task_state and task_spec:
                    task_state.retries = task_spec.max_retries
                    self._set_task_metric_retries(task_id, task_state)
                self.engine.apply_reviewer_result(task_id, False, message, 0, [])
                self._set_task_metric_retries(task_id, self.engine.state.get_task(task_id))
                self.engine._save()
                return
        else:
            review = {"approved": False, "feedback": f"Reviewer error: {error}", "score": 0}

        review = _enforce_review_thresholds(review)
        approved = review.get("approved", False)
        score = review.get("score", 0)
        feedback = review.get("feedback", "")
        blocking_issues = review.get("blocking_issues", [])

        if task_metric:
            task_metric.review_score = score
            task_metric.review_approved = approved
            task_metric.review_issues_count = len(blocking_issues)

        task_state = self.engine.state.get_task(task_id)
        if task_state and _apply_hard_blocks(review, task_state):
            print(f"  ↓ [reviewer] task {task_id}  HARD BLOCK: {task_state.hard_block_reason}")
            self.engine.state.log_event("hard_block", task_id, task_state.hard_block_reason)
            _record_usage(self.ledger, task_id, output if success else "")
            delta_tokens_in, delta_tokens_out, delta_cost_usd = self._apply_task_totals(task_id, task_state)
            if task_state.attempt_history:
                last_attempt = task_state.attempt_history[-1]
                last_attempt["review"] = task_state.hard_block_reason
                last_attempt["score"] = 0
                last_attempt["tokens_in"] = last_attempt.get("tokens_in", 0) + delta_tokens_in
                last_attempt["tokens_out"] = last_attempt.get("tokens_out", 0) + delta_tokens_out
                last_attempt["cost_usd"] = round(last_attempt.get("cost_usd", 0.0) + delta_cost_usd, 6)
            self.engine._save()
            return

        print(f"  ↓ [reviewer] task {task_id}  approved={approved}  score={score}")
        if not approved and feedback:
            print(f"    feedback: {feedback[:200]}")
        _record_usage(self.ledger, task_id, output if success else "")
        if task_state:
            delta_tokens_in, delta_tokens_out, delta_cost_usd = self._apply_task_totals(task_id, task_state)
            if task_state.attempt_history:
                last_attempt = task_state.attempt_history[-1]
                last_attempt["review"] = feedback
                last_attempt["score"] = score
                last_attempt["tokens_in"] = last_attempt.get("tokens_in", 0) + delta_tokens_in
                last_attempt["tokens_out"] = last_attempt.get("tokens_out", 0) + delta_tokens_out
                last_attempt["cost_usd"] = round(last_attempt.get("cost_usd", 0.0) + delta_cost_usd, 6)

        self.engine.apply_reviewer_result(task_id, approved, feedback, score, blocking_issues)
        self._set_task_metric_retries(task_id, self.engine.state.get_task(task_id))
        self.engine._save()

    def _collect(self) -> None:
        done_keys = [key for key, (future, _) in self.in_flight.items() if future.done()]
        for key in done_keys:
            future, action = self.in_flight.pop(key)
            role = action.role
            task_id = action.task_id

            try:
                success, output, error, returned_session_id, token_event = future.result()
            except Exception as exc:
                from agentforce.core.token_event import TokenEvent

                success, output, error, returned_session_id, token_event = (
                    False,
                    "",
                    str(exc),
                    None,
                    TokenEvent(0, 0, 0.0),
                )

            if returned_session_id:
                if role == "worker" and task_id not in self.session_ids:
                    self.session_ids[task_id] = returned_session_id
                elif role == "reviewer" and f"{task_id}_reviewer" not in self.session_ids:
                    self.session_ids[f"{task_id}_reviewer"] = returned_session_id

            if role == "worker":
                self._handle_worker_completion(task_id, success, output, error, token_event)
            elif role == "reviewer":
                self._handle_reviewer_completion(task_id, success, output, error)

    def _handle_human_intervention(self, action) -> None:
        print(f"  ⚠ Human intervention [{action.task_id}]: {getattr(action, 'message', '')[:120]}")
        if getattr(action, "kind", "") == "destructive_action":
            options = getattr(action, "options", []) or []
            for option in options:
                print(f"    - {option.get('id')}: {option.get('label')}")
            print("    Waiting for operator decision in Mission Control.")
            self.engine._save()
            return

        print(f"    Auto-resolving with reviewer context.")
        self.engine.apply_human_resolution(
            action.task_id,
            getattr(action, "message", "Fix the blocking issues listed above."),
        )
        self.engine._save()

    def _process_actions(self, actions) -> None:
        for action in actions:
            role = getattr(action, "role", "")
            if role in ("worker", "reviewer") and hasattr(action, "context"):
                self._submit(action)
            elif hasattr(action, "message"):
                self._handle_human_intervention(action)

    def _handle_idle_state(self, actions) -> bool:
        if not actions and not self.in_flight:
            next_retry_delay = _next_retry_delay_seconds(self.engine)
            if next_retry_delay is not None:
                self.idle_ticks = 0
                if self.tick % 5 == 0 or next_retry_delay <= 2:
                    print(f"  waiting for retry backoff ({next_retry_delay:.1f}s remaining)")
                return False
            self.idle_ticks += 1
            if self.idle_ticks >= 3:
                print(f"\n  No actions and nothing in flight — stopping.")
                return True
        else:
            self.idle_ticks = 0
        return False

    def _print_active_agents(self) -> None:
        active = len(self.in_flight)
        if self.tick % 5 == 0 and active:
            print(f"  [tick {self.tick}] {active} agent(s) running: {list(self.in_flight)}")

    def _pause_if_needed(self) -> None:
        if is_paused(self.engine.state.mission_id):
            print(f"  ⏸  Mission paused. Remove pause file or run: mission resume {self.engine.state.mission_id}")
            self.engine.state.reset_active_tick_clock()
            self.engine._save()
            while is_paused(self.engine.state.mission_id):
                time.sleep(2)
            print(f"  ▶  Mission resumed.")

    def _should_stop(self) -> bool:
        if self.engine.is_done() and not self.in_flight:
            print(f"\n✓ Mission complete! ({self.tick} ticks)")
            return True

        if self.engine.is_failed() and not self.in_flight:
            if "budget" in self.engine.state.caps_hit:
                total_cost = sum(task_state.cost_usd for task_state in self.engine.state.task_states.values())
                cap = self.engine.state.caps.max_cost_usd
                print(f"\nBudget cap exceeded: ${total_cost:.4f} >= max_cost_usd=${cap:.2f}. Halting.")
            else:
                print(f"\n✗ Mission failed. ({self.tick} ticks)")
            return True

        return False

    def run(self, max_ticks: int) -> int:
        with ThreadPoolExecutor(max_workers=self.eff_pool) as executor:
            self.executor = executor
            while self.tick < max_ticks:
                self.tick += 1
                self._collect()
                if self._should_stop():
                    break
                actions = self.engine.tick()
                self._process_actions(actions)
                if self._handle_idle_state(actions):
                    break
                self._print_active_agents()
                self._pause_if_needed()
                time.sleep(2)
        return self.tick


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
    from agentforce.core.token_ledger import TokenLedger
    from agentforce.memory import Memory
    from agentforce.telemetry import TelemetryStore, TaskMetrics

    state_file = Path.home() / ".agentforce" / "state" / f"{mission_id}.json"
    if not state_file.exists():
        print(f"No mission state found: {mission_id}")
        sys.exit(1)

    from agentforce.core.spec import TaskStatus

    memory = Memory(Path.home() / ".agentforce" / "memory")
    engine = MissionEngine.load(state_file, memory)
    worker_runtime, reviewer_runtime = _resolve_execution_defaults(engine, agent, model, variant)

    resolved_agent = worker_runtime.agent
    eff_model = worker_runtime.model
    eff_variant = worker_runtime.thinking

    if extend_caps:
        _apply_extend_caps(engine)

    _reset_resumable_tasks(engine)

    engine._save()
    tele_store = TelemetryStore(_agentforce_home() / "telemetry")

    eff_pool = max(pool_size, engine.state.caps.max_concurrent_workers * 2 + 2)
    _wdir = workdir or engine.state.working_dir
    _print_startup_banner(engine, _wdir, resolved_agent, eff_model, eff_variant, eff_pool)

    ledger = TokenLedger()
    _seed_ledger_from_state(ledger, engine.state.task_states)
    runner = _AutonomousRunner(
        engine=engine,
        workdir=_wdir,
        resolved_agent=resolved_agent,
        model=eff_model,
        variant=eff_variant,
        eff_pool=eff_pool,
        ledger=ledger,
        task_metrics_cls=TaskMetrics,
        task_status_cls=TaskStatus,
    )
    tick = runner.run(max_ticks)

    # Warn if we exited only because the tick limit was reached
    if tick >= max_ticks and not engine.is_done() and not engine.is_failed():
        approved = _count_review_approved_tasks(engine.state.task_states)
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
    mission_metrics = _build_mission_metrics(engine, runner.task_metrics, end.isoformat())
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
        help="Agent CLI to use (default: auto — gemini > claude > opencode)",
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
