"""Mission Engine — the daemon loop that drives a mission to completion.

This is the supervisor brain: it polls for work, dispatches tasks, checks caps,
escaltates to human when needed, and determines when the mission is done.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .event_bus import EVENT_BUS
from agentforce.review.schemas import MissionReviewPayloadV1
from .destructive_actions import (
    DESTRUCTIVE_ACTION_KIND,
    DESTRUCTIVE_ACTION_OPTIONS,
    parse_destructive_action_request,
)
from .state import MissionState, TaskState
from .spec import ExecutionConfig, ExecutionProfile, MissionSpec, TaskSpec, TaskStatus

logger = logging.getLogger("agentforce.engine")

BACKOFF_BASE_SECONDS = 5
BACKOFF_MAX_SECONDS = 60
DEFAULT_RUNTIME_AGENT = "opencode"
DEFAULT_RUNTIME_MODEL = "opencode/nemotron-3-super-free"
DEFAULT_RUNTIME_THINKING = "high"
_RUNTIME_MODEL_FALLBACKS = {
    "opencode": DEFAULT_RUNTIME_MODEL,
    "claude": "claude-sonnet-4-6",
    "codex": "gpt-5.4",
    "gemini": "auto",
}


def detect_runtime_agent() -> str:
    """Choose the first available local runtime provider.

    Fall back to the default runtime when connectors are unavailable so engine
    construction, mission loading, and CLI/state operations remain usable in
    restricted environments and tests.
    """
    from agentforce.connectors import claude as _cl
    from agentforce.connectors import gemini as _gm
    from agentforce.connectors import opencode as _oc

    if _gm.available():
        return "gemini"
    if _cl.available():
        return "claude"
    if _oc.available():
        return "opencode"
    logger.warning(
        "No AI provider connectors available (gemini, claude, or opencode); "
        "falling back to default runtime agent %s",
        DEFAULT_RUNTIME_AGENT,
    )
    return DEFAULT_RUNTIME_AGENT


def _model_matches_agent(agent: str, model: str | None) -> bool:
    if not model:
        return False
    if agent == "gemini":
        return model == "auto" or model in {"pro", "flash", "flash-lite"} or model.startswith("gemini-")
    if agent == "claude":
        return model.startswith("claude-")
    if agent == "codex":
        return not (
            model.startswith("claude-")
            or model.startswith("gemini-")
            or model in {"auto", "pro", "flash", "flash-lite"}
            or model.startswith("opencode/")
        )
    return True


def normalize_runtime_profile(
    *,
    agent: str | None = None,
    model: str | None = None,
    thinking: str | None = None,
) -> ExecutionProfile:
    resolved_agent = agent or detect_runtime_agent()
    resolved_model = model.strip() if isinstance(model, str) and model.strip() else None
    if not _model_matches_agent(resolved_agent, resolved_model):
        resolved_model = _RUNTIME_MODEL_FALLBACKS.get(resolved_agent, DEFAULT_RUNTIME_MODEL)
    return ExecutionProfile(
        agent=resolved_agent,
        model=resolved_model,
        thinking=thinking or DEFAULT_RUNTIME_THINKING,
    )


# ── Delegation descriptors ──

@dataclass
class WorkerDelegation:
    """Descriptor for a worker agent to dispatch."""
    task_id: str
    role: str = "worker"
    goal: str = ""
    context: str = ""
    toolsets: list[str] = field(default_factory=lambda: ["terminal", "file"])
    agent: Optional[str] = None
    model: Optional[str] = None
    thinking: Optional[str] = None
    timeout: int = 300


@dataclass
class ReviewerDelegation:
    """Descriptor for a reviewer agent to dispatch."""
    task_id: str
    role: str = "reviewer"
    goal: str = ""
    context: str = ""
    toolsets: list[str] = field(default_factory=lambda: ["file"])
    agent: Optional[str] = None
    model: Optional[str] = None
    thinking: Optional[str] = None
    timeout: int = 120


@dataclass
class HumanIntervention:
    """When the engine needs human attention."""
    task_id: str
    message: str
    suggestions: list[str] = field(default_factory=list)
    kind: str = ""
    options: list[dict] = field(default_factory=list)


class MissionEngine:
    """Drives a mission from start to completion via state machine ticks.

    Usage:
        engine = MissionEngine(spec, state_dir, memory)

        # Each tick:
        actions = engine.tick()

        # Engine returns actions the caller should execute:
        # - WorkerDelegations to dispatch as delegate_task
        # - ReviewerDelegations to dispatch as delegate_task
        # - HumanInterventions if resolution is needed

        # After workers/reviewers complete:
        engine.apply_worker_result(task_id, success, output)
        engine.apply_reviewer_result(task_id, approved, feedback)
        engine.apply_human_resolution(task_id, message)

        # Check completion:
        if engine.is_done():
            print("MISSION ACCOMPLISHED")
        if engine.needs_human():
            print("HUMAN INTERVENTION REQUIRED")
    """

    def __init__(
        self,
        spec: MissionSpec,
        state_dir: str | Path,
        memory,  # agentforce.memory.Memory
        mission_id: str = None,
        worker_model: str = None,
        reviewer_model: str = None,
    ):
        issues = spec.validate(
            stage="launch",
            worker_model_override=worker_model,
            reviewer_model_override=reviewer_model,
        )
        if issues:
            raise ValueError("; ".join(issues))

        self.spec = spec
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.memory = memory
        self.worker_model = worker_model
        self.reviewer_model = reviewer_model

        mid = mission_id or spec.short_id()
        self.state = MissionState(mission_id=mid, spec=spec)
        self.state.working_dir = str(Path(spec.working_dir or f"./missions-{mid}").resolve())
        self.state.execution_defaults = self._normalized_execution_defaults()
        self._sync_execution_telemetry()

        # Initialize task states
        for ts in spec.tasks:
            self.state.task_states[ts.id] = TaskState(
                task_id=ts.id,
                spec_summary=f"{ts.title}"[:200],
            )

        self.state.log_event("mission_started", details=f"Started mission: {spec.name}")
        self._state_file = self.state_dir / f"{mid}.json"
        self._review_payload_emitted = False
        self._save()

        logger.info("Engine initialized: %s [%s]", spec.name, mid)

    @classmethod
    def create(
        cls,
        spec: MissionSpec,
        state_dir: str | Path,
        memory,
        mission_id: str = None,
        worker_model: str = None,
        reviewer_model: str = None,
    ) -> MissionEngine:
        """Factory kept for CLI and public API compatibility."""
        return cls(
            spec=spec,
            state_dir=state_dir,
            memory=memory,
            mission_id=mission_id,
            worker_model=worker_model,
            reviewer_model=reviewer_model,
        )

    # ── Persistence ──

    def _save(self):
        self.state.save(self._state_file)
        try:
            EVENT_BUS.publish(
                "mission.snapshot",
                {"mission_id": self.state.mission_id, "state": self.state.to_dict()},
            )
            EVENT_BUS.publish(
                "mission.list_snapshot",
                {"missions": [self.state.to_summary_dict()]},
            )
            EVENT_BUS.publish(
                "mission.cost_updated",
                {
                    "mission_id": self.state.mission_id,
                    "tokens_in": self.state.tokens_in,
                    "tokens_out": self.state.tokens_out,
                    "cost_usd": self.state.cost_usd,
                },
            )
        except Exception:
            pass

    @property
    def state_file(self) -> Path:
        return self._state_file

    @classmethod
    def load(cls, state_file: str | Path, memory) -> MissionEngine:
        """Resume an engine from a saved state file."""
        state = MissionState.load(state_file)
        engine = cls.__new__(cls)
        engine.spec = state.spec
        engine.state_dir = Path(state_file).parent
        engine.memory = memory
        engine.worker_model = None
        engine.reviewer_model = None
        engine.state = state
        engine._state_file = Path(state_file)
        engine._review_payload_emitted = False
        engine._sync_execution_telemetry()
        return engine

    def _log_event(self, event_type: str, task_id: str | None = None, details: str = "") -> None:
        self.state.log_event(event_type, task_id, details)
        try:
            EVENT_BUS.publish(
                "mission.event_logged",
                {
                    "mission_id": self.state.mission_id,
                    "entry": self.state.event_log[-1].to_dict(),
                },
            )
        except Exception:
            pass

    def _publish_task_update(self, task_id: str) -> None:
        task = self.state.get_task(task_id)
        if task is None:
            return
        try:
            EVENT_BUS.publish(
                "mission.task_updated",
                {
                    "mission_id": self.state.mission_id,
                    "task_id": task_id,
                    "task": task.to_dict(),
                },
            )
            EVENT_BUS.publish(
                "task.cost_updated",
                {
                    "mission_id": self.state.mission_id,
                    "task_id": task_id,
                    "tokens_in": task.tokens_in,
                    "tokens_out": task.tokens_out,
                    "cost_usd": task.cost_usd,
                },
            )
        except Exception:
            pass

    def _emit_review_payload_ready(self) -> None:
        if self._review_payload_emitted or self.state.completed_at is None:
            return
        payload = MissionReviewPayloadV1.from_state(self.state)
        try:
            EVENT_BUS.publish(
                "mission.review_payload_ready",
                {
                    "mission_id": self.state.mission_id,
                    "payload": payload.to_dict(),
                },
            )
        finally:
            self._review_payload_emitted = True

    def _cli_execution_profile(self, role: str) -> Optional[ExecutionProfile]:
        model = self.worker_model if role == "worker" else self.reviewer_model
        if not model:
            return None
        return ExecutionProfile(model=model)

    def _runtime_fallback_profile(self) -> ExecutionProfile:
        return normalize_runtime_profile()

    def _normalized_execution_defaults(self) -> ExecutionConfig:
        return ExecutionConfig(
            worker=self.spec.resolve_execution_profile(
                TaskSpec(id="__defaults__", title="", description=""),
                "worker",
                cli_default=self._cli_execution_profile("worker"),
                runtime_fallback=self._runtime_fallback_profile(),
            ),
            reviewer=self.spec.resolve_execution_profile(
                TaskSpec(id="__defaults__", title="", description=""),
                "reviewer",
                cli_default=self._cli_execution_profile("reviewer"),
                runtime_fallback=self._runtime_fallback_profile(),
            ),
        )

    def _resolve_execution_profile(
        self,
        task_spec: TaskSpec,
        role: str,
        runtime_fallback: Optional[ExecutionProfile] = None,
    ) -> Optional[ExecutionProfile]:
        return self.spec.resolve_execution_profile(
            task_spec,
            role,
            mission_defaults=self.state.resolved_execution_defaults(),
            cli_default=self._cli_execution_profile(role),
            runtime_fallback=runtime_fallback or self._runtime_fallback_profile(),
        )

    def _sync_execution_telemetry(self) -> None:
        defaults = self.state.resolved_execution_defaults()
        worker = defaults.worker
        self.state.worker_agent = worker.agent if worker and worker.agent else ""
        self.state.worker_model = worker.model if worker and worker.model else ""

    # ── Caps ──

    def _check_caps(self) -> Optional[str]:
        hit = self.state.check_caps()
        if hit:
            logger.warning("Cap hit: %s", hit)
            self.state.log_event("mission_cap_hit", details=hit)
            self._save()
        return hit

    # ── MAIN TICK ──
    #
    # Each call to tick() returns a list of action descriptors that the
    # caller should dispatch. The caller feeds results back via
    # apply_worker_result/apply_reviewer_result/apply_human_resolution.

    def tick(self) -> list:
        """One scheduler iteration. Returns list of actions to dispatch.

        Returns:
            list of WorkerDelegation | ReviewerDelegation | HumanIntervention
        """
        actions = []

        if self.is_done():
            if self.state.completed_at is None:
                self.state.completed_at = datetime.now(timezone.utc).isoformat()
                self._log_event("mission_completed", details="All tasks review approved")
                if self.state.spec.caps.review == "disabled":
                    self._log_event("review_skipped", details="Review disabled in caps")
                self._save()
                self._emit_review_payload_ready()
            return actions

        if self.is_failed():
            if self.state.completed_at is None:
                self.state.completed_at = datetime.now(timezone.utc).isoformat()
                self._log_event("mission_failed", details="Mission already failed")
                if self.state.spec.caps.review == "disabled":
                    self._log_event("review_skipped", details="Review disabled in caps")
                self._save()
                self._emit_review_payload_ready()
            return actions

        self.state.record_active_tick()

        # Check caps
        cap_hit = self._check_caps()
        if cap_hit:
            self._log_event("mission_failed", details=cap_hit)
            if self.state.spec.caps.review == "disabled":
                self._log_event("review_skipped", details="Review disabled in caps")
            if self.state.completed_at is None:
                self.state.completed_at = datetime.now(timezone.utc).isoformat()
            self._save()
            self._emit_review_payload_ready()
            return actions  # Stop all activity

        # Human interventions first — if we're past the limit, fail the mission
        if self.state.interventions_exhausted() and self.state.needs_human():
            self._log_event("mission_failed", details="Intervention limit exhausted")
            if self.state.spec.caps.review == "disabled":
                self._log_event("review_skipped", details="Review disabled in caps")
            if self.state.completed_at is None:
                self.state.completed_at = datetime.now(timezone.utc).isoformat()
            self._save()
            self._emit_review_payload_ready()
            return actions

        # Surface any human interventions
        for tid in self.state.needs_human():
            ts = self.state.get_task(tid)
            actions.append(HumanIntervention(
                task_id=tid,
                message=ts.human_intervention_message or f"Task {tid} requires human attention",
                kind=ts.human_intervention_kind,
                options=ts.human_intervention_options,
            ))

        # Try to dispatch workers for pending tasks
        if self.state.workers_available():
            dispatchable = self.state.dispatchable_tasks()
            for tid in dispatchable:
                if self.state.worker_count() >= self.state.caps.max_concurrent_workers:
                    break
                task_state = self.state.get_task(tid)
                if task_state and task_state.retry_not_before and time.time() < task_state.retry_not_before:
                    logger.debug(
                        "task %s in backoff — eligible at %.1fs",
                        tid,
                        task_state.retry_not_before - time.time(),
                    )
                    continue
                action = self._dispatch_worker(tid)
                if action:
                    actions.append(action)

        # Try to dispatch reviewers for completed work
        reviewable = self.state.reviewable_tasks()
        for tid in reviewable:
            action = self._dispatch_reviewer(tid)
            if action:
                actions.append(action)

        self._save()
        return actions

    def _dispatch_worker(self, task_id: str) -> Optional[WorkerDelegation]:
        """Create a worker delegation for a task."""
        task_spec = self._get_task_spec(task_id)
        ts = self.state.get_task(task_id)
        if not ts or not ts.can_progress():
            return None

        ts.status = TaskStatus.IN_PROGRESS
        ts.started_at = datetime.now(timezone.utc).isoformat()
        ts.human_intervention_needed = False
        ts.blocking_issues = []
        ts.bump()

        # Build context with memory
        query_text = "\n".join(task_spec.acceptance_criteria) if task_spec.acceptance_criteria else task_spec.description
        logger.debug("agent_context query [%s]: %s", task_id, query_text)
        mem_context = self.memory.agent_context(self.state.mission_id, task_id, query=query_text)

        prompt = task_spec.generate_worker_prompt()
        if mem_context:
            prompt += f"\n\nMEMORY CONTEXT:\n{mem_context}"

        if self.state.destructive_action_allow_rules:
            prompt += "\n\nMISSION-SCOPED DESTRUCTIVE ACTION ALLOW RULES:\n"
            for key, rule in sorted(self.state.destructive_action_allow_rules.items()):
                guidance = rule.get("guidance") or "Previously approved by the operator."
                action = rule.get("proposed_action") or key
                prompt += f"- action_key={key}: {action}. {guidance}\n"

        if ts.timeout_output:
            prompt += f"\n\nPRIOR CONTEXT: The previous run did not complete. The output produced so far is included below — use it as context to continue from where it left off rather than starting from scratch:\n<prior_output>\n{ts.timeout_output}\n</prior_output>"

        if ts.retries > 0:
            prompt += f"\n\nPREVIOUS ATTEMPT FAILED (attempt {ts.retries + 1} of {task_spec.max_retries + 1})."
            if ts.review_feedback:
                prompt += f"\nReviewer feedback: {ts.review_feedback}"
            if ts.blocking_issues:
                prompt += "\nBlocking issues that MUST be fixed:\n" + "\n".join(f"- {i}" for i in ts.blocking_issues)
            if ts.error_message:
                prompt += f"\nPrevious error: {ts.error_message}"

        self._log_event("task_dispatched", task_id, f"Worker dispatched for {task_spec.title}")
        self._publish_task_update(task_id)
        EVENT_BUS.publish(
            "task.attempt_started",
            {
                "mission_id": self.state.mission_id,
                "task_id": task_id,
                "attempt_number": ts.retries + 1,
            },
        )
        logger.info("Dispatching worker: %s - %s", task_id, task_spec.title)
        execution = self._resolve_execution_profile(task_spec, "worker")
        logger.debug("task %s worker model: %s", task_id, execution.model if execution else None)

        return WorkerDelegation(
            task_id=task_id,
            goal=f"Complete task {task_id}: {task_spec.title}",
            context=prompt,
            agent=execution.agent if execution else None,
            model=execution.model if execution else None,
            thinking=execution.thinking if execution else None,
            timeout=min(600, self.state.caps.max_wall_time_minutes * 60) if self.state.caps.max_wall_time_minutes else 600,
        )

    def _dispatch_reviewer(self, task_id: str) -> Optional[ReviewerDelegation]:
        """Create a reviewer delegation for a task."""
        task_spec = self._get_task_spec(task_id)
        ts = self.state.get_task(task_id)
        if not ts or not ts.can_review():
            return None

        ts.status = TaskStatus.REVIEWING
        ts.bump()

        # Build review context with memory
        query_text = "\n".join(task_spec.acceptance_criteria) if task_spec.acceptance_criteria else task_spec.description
        logger.debug("agent_context query [%s]: %s", task_id, query_text)
        mem_context = self.memory.agent_context(self.state.mission_id, task_id, query=query_text)

        prompt = task_spec.generate_reviewer_prompt(
            worker_output=ts.worker_output,
            mission_name=self.state.spec.name,
            dod="; ".join(self.state.spec.definition_of_done),
            project_memory=mem_context,
        )

        self._log_event("review_started", task_id, f"Review started for {task_spec.title}")
        self._publish_task_update(task_id)
        logger.info("Dispatching reviewer: %s", task_id)
        execution = self._resolve_execution_profile(task_spec, "reviewer")

        return ReviewerDelegation(
            task_id=task_id,
            goal=f"Review task {task_id}: {task_spec.title}",
            context=prompt,
            agent=execution.agent if execution else None,
            model=execution.model if execution else None,
            thinking=execution.thinking if execution else None,
            timeout=120,
        )

    # ── Result application ──

    def apply_worker_result(self, task_id: str, success: bool, output: str = "", error: str = ""):
        """Feed back a worker result."""
        ts = self.state.get_task(task_id)
        if not ts:
            raise ValueError(f"Unknown task: {task_id}")

        task_spec = self._get_task_spec(task_id)
        ts.bump()
        ts.timeout_output = ""  # clear any saved timeout context now that we have a real result

        if success:
            destructive_request = parse_destructive_action_request(output)
            if destructive_request:
                self.request_destructive_action(task_id, destructive_request, output=output)
                return

        if success:
            ts.worker_output = output
            ts.status = TaskStatus.COMPLETED
            ts.retry_not_before = 0.0
            self._log_event("task_completed", task_id, f"Worker completed {task_spec.title}")
            logger.info("Worker completed: %s", task_id)
        else:
            ts.error_message = error or "Worker reported failure"
            ts.retries += 1
            ts.lifetime_retries += 1
            self.state.total_retries += 1
            self.state.lifetime_retries += 1

            # Check if we can retry
            if ts.retries >= task_spec.max_retries or self.state.total_retries >= self.state.caps.max_retries_global:
                ts.status = TaskStatus.FAILED
                ts.retry_not_before = 0.0
                self._log_event("task_failed", task_id, ts.error_message)
                logger.warning("Task failed permanently: %s", task_id)
            else:
                backoff = min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * (2 ** (ts.retries - 1)))
                ts.status = TaskStatus.RETRY
                ts.retry_not_before = time.time() + backoff
                self._log_event("task_retry", task_id, f"Retry {ts.retries}/{task_spec.max_retries}")
                logger.info("Retrying task: %s (attempt %d)", task_id, ts.retries + 1)

        self._publish_task_update(task_id)
        self._save()

    def apply_reviewer_result(self, task_id: str, approved: bool, feedback: str = "", score: int = 0, blocking_issues: list = None, suggestions: list = None):
        """Feed back a reviewer result."""
        ts = self.state.get_task(task_id)
        if not ts:
            raise ValueError(f"Unknown task: {task_id}")
        task_spec = self._get_task_spec(task_id)
        ts.bump()

        ts.review_feedback = feedback
        ts.review_score = score or (10 if approved else 3)
        # Only overwrite blocking_issues when the reviewer provides a non-empty list;
        # keep the previous list if the reviewer didn't supply new ones, so the worker
        # retains the structured issue context across retries.
        if blocking_issues:
            ts.blocking_issues = blocking_issues
        elif approved:
            ts.blocking_issues = []

        if approved:
            ts.status = TaskStatus.REVIEW_APPROVED
            ts.retry_not_before = 0.0
            ts.completed_at = datetime.now(timezone.utc).isoformat()
            self.memory.task_clear(task_id)  # Clean ephemeral memory
            self._log_event("review_approved", task_id, feedback)
            logger.info("Task review approved: %s", task_id)

            # Update project memory with lessons learned
            if feedback:
                self.memory.project_set(
                    self.state.mission_id,
                    f"task_{task_id}_outcome",
                    feedback[:2000],
                    category="fact"
                )
        else:
            ts.retries += 1
            ts.lifetime_retries += 1
            self.state.total_retries += 1
            self.state.lifetime_retries += 1

            # Escalate to human only after retries are exhausted
            if ts.retries >= task_spec.max_retries or self.state.total_retries >= self.state.caps.max_retries_global:
                if blocking_issues:
                    ts.human_intervention_needed = True
                    ts.human_intervention_message = (
                        f"Reviewer blocked on task {task_id}: "
                        f"{'; '.join(blocking_issues)}\n"
                        f"Feedback: {feedback}"
                    )
                    ts.status = TaskStatus.NEEDS_HUMAN
                    ts.retry_not_before = 0.0
                    self.state.total_human_interventions += 1
                    self.state.lifetime_human_interventions += 1
                    self._log_event("human_intervention", task_id, ts.human_intervention_message)
                    logger.warning("Human intervention needed: %s", task_id)
                else:
                    ts.status = TaskStatus.FAILED
                    ts.retry_not_before = 0.0
                    self._log_event("task_failed", task_id, f"Max retries exceeded: {feedback}")
                    logger.warning("Task failed after retries: %s", task_id)
            else:
                backoff = min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * (2 ** (ts.retries - 1)))
                ts.status = TaskStatus.RETRY
                ts.retry_not_before = time.time() + backoff
                self._log_event("review_rejected", task_id, f"Retry {ts.retries}/{task_spec.max_retries}: {feedback}")
                logger.info("Task rejected, will retry: %s (score: %d)", task_id, score)

        self._publish_task_update(task_id)
        self._save()

    def _clear_human_intervention(self, ts: TaskState) -> None:
        ts.human_intervention_needed = False
        ts.human_intervention_message = ""
        ts.human_intervention_kind = ""
        ts.human_intervention_options = []
        ts.human_intervention_context = {}

    def request_destructive_action(self, task_id: str, request: dict, output: str = "") -> bool:
        """Pause a worker for operator approval before a destructive action.

        Returns True when human input is required and False when a mission-level
        allow rule auto-resolved the request.
        """
        ts = self.state.get_task(task_id)
        if not ts:
            raise ValueError(f"Unknown task: {task_id}")

        action_key = str(request.get("action_key") or "").strip()
        if not action_key:
            raise ValueError("action_key is required")

        ts.worker_output = output or ts.worker_output
        if output:
            if not ts.attempt_history or ts.attempt_history[-1].get("output") != output:
                ts.attempt_history.append({
                    "attempt_number": len(ts.attempt_history) + 1,
                    "output": output,
                    "intervention_kind": DESTRUCTIVE_ACTION_KIND,
                })
            else:
                ts.attempt_history[-1]["intervention_kind"] = DESTRUCTIVE_ACTION_KIND

        allow_rule = self.state.destructive_action_allow_rules.get(action_key)
        if allow_rule:
            self._clear_human_intervention(ts)
            ts.status = TaskStatus.RETRY
            ts.retry_not_before = 0.0
            guidance = allow_rule.get("guidance") or "Previously approved by the operator."
            ts.review_feedback = (
                ts.review_feedback
                + f"\n\nHuman guidance: Previously approved destructive action {action_key}. {guidance}"
            ).strip()
            ts.bump()
            self._log_event(
                "destructive_action_auto_allowed",
                task_id,
                f"Auto-allowed destructive action {action_key}",
            )
            self._publish_task_update(task_id)
            self._save()
            return False

        was_already_waiting = ts.needs_human_attention()
        ts.status = TaskStatus.NEEDS_HUMAN
        ts.human_intervention_needed = True
        ts.human_intervention_kind = DESTRUCTIVE_ACTION_KIND
        ts.human_intervention_context = dict(request)
        ts.human_intervention_options = [dict(option) for option in DESTRUCTIVE_ACTION_OPTIONS]
        ts.human_intervention_message = (
            f"Potential destructive action requested: {request.get('summary', action_key)}\n"
            f"Risk: {request.get('risk', 'Unknown risk')}\n"
            f"Action: {request.get('proposed_action', action_key)}"
        )
        ts.error_message = ""
        ts.retry_not_before = 0.0
        ts.bump()
        if not was_already_waiting:
            self.state.total_human_interventions += 1
            self.state.lifetime_human_interventions += 1
        self._log_event("human_intervention", task_id, ts.human_intervention_message)
        logger.warning("Destructive action approval needed: %s", task_id)
        self._publish_task_update(task_id)
        self._save()
        return True

    def _destructive_resolution_guidance(self, ts: TaskState, choice_id: str, resolution: str) -> str:
        context = ts.human_intervention_context or {}
        action_key = context.get("action_key", "")
        proposed = context.get("proposed_action", action_key)
        label = next(
            (option.get("label", choice_id) for option in ts.human_intervention_options if option.get("id") == choice_id),
            choice_id,
        )

        if choice_id == "revise" and not resolution.strip():
            raise ValueError("message is required for revise")
        if choice_id == "always_allow":
            self.state.destructive_action_allow_rules[action_key] = {
                **context,
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "guidance": resolution.strip() or "Operator allowed this exact destructive action for this mission.",
            }

        if choice_id == "approve_once":
            default = f"Approved once for action_key={action_key}: {proposed}"
        elif choice_id == "always_allow":
            default = f"Always allow action_key={action_key}: {proposed}"
        elif choice_id == "deny":
            default = f"Denied action_key={action_key}: do not perform {proposed}; find a safer alternative."
        else:
            default = resolution.strip()

        suffix = f" Operator note: {resolution.strip()}" if resolution.strip() and choice_id != "revise" else ""
        return f"Destructive action decision: {label}. {default}{suffix}"

    def apply_human_resolution(self, task_id: str, resolution: str, choice_id: str | None = None):
        """Apply human intervention for a blocked task."""
        ts = self.state.get_task(task_id)
        if not ts:
            raise ValueError(f"Unknown task: {task_id}")

        if not ts.needs_human_attention():
            raise ValueError(f"Task {task_id} doesn't need human attention")

        if ts.human_intervention_kind == DESTRUCTIVE_ACTION_KIND:
            valid_choices = {option.get("id") for option in ts.human_intervention_options}
            if not isinstance(choice_id, str) or choice_id not in valid_choices:
                raise ValueError("valid choice_id is required")
            resolution = self._destructive_resolution_guidance(ts, choice_id, resolution or "")

        self._clear_human_intervention(ts)
        ts.status = TaskStatus.RETRY
        ts.retry_not_before = 0.0
        # Preserve the reviewer's feedback and blocking_issues so the worker
        # sees the structured issues on retry. Append human guidance only if
        # it adds information beyond the reviewer verdict.
        if resolution:
            ts.review_feedback = ts.review_feedback + f"\n\nHuman guidance: {resolution}"
        ts.bump()

        self._log_event("human_resolved", task_id, resolution)
        logger.info("Human resolved task: %s", task_id)
        self._publish_task_update(task_id)
        self._save()

    def resolve_as_failed(self, task_id: str):
        """Mark a human-blocked task as permanently failed."""
        ts = self.state.get_task(task_id)
        if not ts:
            raise ValueError(f"Unknown task: {task_id}")

        ts.status = TaskStatus.FAILED
        self._clear_human_intervention(ts)
        ts.retry_not_before = 0.0
        ts.bump()

        self._log_event("task_failed", task_id, "Marked as failed by human")
        self._publish_task_update(task_id)
        self._save()

    def manual_retry(self, task_id: str) -> None:
        """Reset a failed or stuck task back to pending/retry and restart its budget."""
        ts = self.state.get_task(task_id)
        if not ts:
            raise ValueError(f"Unknown task: {task_id}")

        status = getattr(ts.status, "value", ts.status)
        retryable = {TaskStatus.FAILED.value, TaskStatus.NEEDS_HUMAN.value, TaskStatus.COMPLETED.value}
        if status not in retryable:
            raise ValueError(f"Task {task_id} cannot be manually retried from status {status!r}")

        self._clear_human_intervention(ts)
        ts.error_message = ""
        # COMPLETED means worker finished but reviewer never ran — reset fully to PENDING.
        # FAILED/NEEDS_HUMAN use RETRY so the worker picks up existing feedback context.
        ts.status = TaskStatus.PENDING if status == TaskStatus.COMPLETED.value else TaskStatus.RETRY
        ts.retry_not_before = 0.0
        ts.bump()
        self._log_event("task_retry", task_id, "Manually retried task; budget reset")
        self._publish_task_update(task_id)
        self._save()

    def append_task(self, spec: TaskSpec) -> None:
        """Appends a new task to the end of the mission specification and initializes its state.
        Useful for troubleshooting or adjusting the trajectory after completion.
        """
        if any(t.id == spec.id for t in self.state.spec.tasks):
            raise ValueError(f"Task with ID {spec.id} already exists in this mission.")
        
        # Append to the spec
        self.state.spec.tasks.append(spec)
        
        # Initialize state
        self.state.task_states[spec.id] = TaskState(
            task_id=spec.id,
            spec_summary=f"{spec.title} — {spec.description[:200]}...",
            status=TaskStatus.PENDING
        )
        
        # Reset the finished_at flag if it was set, effectively reopening the mission
        self.state.finished_at = None
        self._publish_task_update(spec.id)
        self._save()

    def finish_mission(self) -> None:
        """Mark the mission as officially finished by the user."""
        self.state.finished_at = datetime.now(timezone.utc).isoformat()
        self.state.completed_at = self.state.finished_at
        self._log_event("mission_finished")
        self._save()
        self._emit_review_payload_ready()

    def change_default_models(
        self,
        worker_model: str | None = None,
        reviewer_model: str | None = None,
        worker_agent: str | None = None,
        reviewer_agent: str | None = None,
        worker_thinking: str | None = None,
        reviewer_thinking: str | None = None,
    ) -> dict:
        """Update mission defaults for tasks that have not started yet.

        Started tasks that currently inherit mission defaults are pinned to the
        old resolved defaults so their timeline/history keeps showing the model
        they were already using.
        """
        worker_model = worker_model.strip() if isinstance(worker_model, str) else None
        reviewer_model = reviewer_model.strip() if isinstance(reviewer_model, str) else None
        worker_agent = worker_agent.strip() if isinstance(worker_agent, str) else None
        reviewer_agent = reviewer_agent.strip() if isinstance(reviewer_agent, str) else None
        worker_thinking = worker_thinking.strip() if isinstance(worker_thinking, str) else None
        reviewer_thinking = reviewer_thinking.strip() if isinstance(reviewer_thinking, str) else None
        if not worker_model and not reviewer_model and not worker_agent and not reviewer_agent and not worker_thinking and not reviewer_thinking:
            raise ValueError("worker_model, reviewer_model, worker_agent, reviewer_agent, worker_thinking, or reviewer_thinking is required")

        roles = []
        if worker_model or worker_agent or worker_thinking:
            roles.append("worker")
        if reviewer_model or reviewer_agent or reviewer_thinking:
            roles.append("reviewer")

        old_defaults = self.state.resolved_execution_defaults()
        pinned_tasks = 0
        for task_spec in self.spec.tasks:
            task_state = self.state.get_task(task_spec.id)
            status = getattr(task_state.status, "value", task_state.status) if task_state else "pending"
            has_started = bool(
                status != TaskStatus.PENDING.value
                or getattr(task_state, "started_at", None)
                or getattr(task_state, "worker_output", "")
                or getattr(task_state, "attempt_history", [])
            )
            if not has_started:
                continue

            changed = False
            for role in roles:
                current_profile = getattr(task_spec.execution, role)
                if current_profile and current_profile.configured():
                    continue
                old_profile = getattr(old_defaults, role)
                if old_profile and old_profile.configured():
                    setattr(
                        task_spec.execution,
                        role,
                        ExecutionProfile(
                            agent=old_profile.agent,
                            model=old_profile.model,
                            thinking=old_profile.thinking,
                        ),
                    )
                    changed = True
            if changed:
                pinned_tasks += 1

        defaults = self.state.execution_defaults
        if worker_model or worker_agent or worker_thinking:
            current = defaults.worker or ExecutionProfile()
            defaults.worker = ExecutionProfile(
                agent=worker_agent or current.agent,
                model=worker_model or current.model,
                thinking=worker_thinking or current.thinking,
            )
            self.spec.execution_defaults.worker = defaults.worker
        if reviewer_model or reviewer_agent or reviewer_thinking:
            current = defaults.reviewer or ExecutionProfile()
            defaults.reviewer = ExecutionProfile(
                agent=reviewer_agent or current.agent,
                model=reviewer_model or current.model,
                thinking=reviewer_thinking or current.thinking,
            )
            self.spec.execution_defaults.reviewer = defaults.reviewer

        self._sync_execution_telemetry()
        self._log_event(
            "mission_default_models_changed",
            details=(
                f"worker={worker_agent or '-'}:{worker_model or '-'}:{worker_thinking or '-'} "
                f"reviewer={reviewer_agent or '-'}:{reviewer_model or '-'}:{reviewer_thinking or '-'} pinned={pinned_tasks}"
            ),
        )
        self._save()
        return {
            "worker_agent": self.state.execution_defaults.worker.agent if self.state.execution_defaults.worker else None,
            "worker_model": self.state.execution_defaults.worker.model if self.state.execution_defaults.worker else None,
            "worker_thinking": self.state.execution_defaults.worker.thinking if self.state.execution_defaults.worker else None,
            "reviewer_agent": self.state.execution_defaults.reviewer.agent if self.state.execution_defaults.reviewer else None,
            "reviewer_model": self.state.execution_defaults.reviewer.model if self.state.execution_defaults.reviewer else None,
            "reviewer_thinking": self.state.execution_defaults.reviewer.thinking if self.state.execution_defaults.reviewer else None,
            "pinned_tasks": pinned_tasks,
        }

    def change_models(
        self,
        task_id: str,
        worker_model: str | None = None,
        reviewer_model: str | None = None,
        worker_agent: str | None = None,
        reviewer_agent: str | None = None,
        worker_thinking: str | None = None,
        reviewer_thinking: str | None = None,
    ) -> bool:
        """Change worker and/or reviewer models for a task.

        If the task is still PENDING (never dispatched), only the spec is updated.
        For any other status a worker model change resets and re-queues the task
        from PENDING so the next worker run uses the new model.

        Returns True when a worker retry was triggered, False when only the spec
        was saved.
        """
        worker_model = worker_model.strip() if isinstance(worker_model, str) else None
        reviewer_model = reviewer_model.strip() if isinstance(reviewer_model, str) else None
        worker_agent = worker_agent.strip() if isinstance(worker_agent, str) else None
        reviewer_agent = reviewer_agent.strip() if isinstance(reviewer_agent, str) else None
        worker_thinking = worker_thinking.strip() if isinstance(worker_thinking, str) else None
        reviewer_thinking = reviewer_thinking.strip() if isinstance(reviewer_thinking, str) else None
        if not worker_model and not reviewer_model and not worker_agent and not reviewer_agent and not worker_thinking and not reviewer_thinking:
            raise ValueError("worker_model, reviewer_model, worker_agent, reviewer_agent, worker_thinking, or reviewer_thinking is required")

        task_spec = self._get_task_spec(task_id)
        ts = self.state.get_task(task_id)
        if not ts:
            raise ValueError(f"Unknown task: {task_id}")

        if worker_model or worker_agent or worker_thinking:
            if task_spec.execution.worker is None:
                task_spec.execution.worker = ExecutionProfile(
                    agent=worker_agent,
                    model=worker_model,
                    thinking=worker_thinking,
                )
            else:
                if worker_agent:
                    task_spec.execution.worker.agent = worker_agent
                if worker_model:
                    task_spec.execution.worker.model = worker_model
                if worker_thinking:
                    task_spec.execution.worker.thinking = worker_thinking
            if worker_model:
                task_spec.model = worker_model
        if reviewer_model or reviewer_agent or reviewer_thinking:
            if task_spec.execution.reviewer is None:
                task_spec.execution.reviewer = ExecutionProfile(
                    agent=reviewer_agent,
                    model=reviewer_model,
                    thinking=reviewer_thinking,
                )
            else:
                if reviewer_agent:
                    task_spec.execution.reviewer.agent = reviewer_agent
                if reviewer_model:
                    task_spec.execution.reviewer.model = reviewer_model
                if reviewer_thinking:
                    task_spec.execution.reviewer.thinking = reviewer_thinking

        status = getattr(ts.status, "value", ts.status)
        worker_runtime_changed = bool(worker_model or worker_agent or worker_thinking)
        if status == TaskStatus.PENDING.value or not worker_runtime_changed:
            # Task has never been dispatched — just persist the new model.
            self._save()
            return False

        # Task has already been dispatched at least once; reset and re-queue.
        # Carry forward the best available context so the new model can continue
        # from where the previous one left off rather than starting from scratch.
        ts.timeout_output = ts.worker_output or ts.timeout_output
        self.state.total_retries = max(0, self.state.total_retries - ts.retries)
        ts.retries = 0
        ts.error_message = ""
        self._clear_human_intervention(ts)
        ts.status = TaskStatus.PENDING
        ts.retry_not_before = 0.0
        ts.bump()
        self._log_event(
            "task_model_changed",
            task_id,
            f"Worker runtime changed to agent={worker_agent or '-'} model={worker_model or '-'} thinking={worker_thinking or '-'}, retries reset",
        )
        self._publish_task_update(task_id)
        self._save()
        return True

    def change_model(self, task_id: str, model: str) -> bool:
        """Change the worker model for a task."""
        return self.change_models(task_id, worker_model=model)

    # ── Status queries ──

    def is_done(self) -> bool:
        return self.state.is_done()

    def is_failed(self) -> bool:
        return self.state.is_failed() or bool(self.state.caps_hit)

    def is_blocking(self) -> bool:
        return bool(self.state.needs_human())

    def pending_count(self) -> int:
        return len(self.state.dispatchable_tasks())

    def report(self) -> str:
        """Human-readable status report."""
        lines = [
            f"Mission: {self.spec.name} [{self.state.mission_id}]",
            f"Progress: " + self._progress_bar() + f" {self._done_count()}/{len(self.spec.tasks)}",
            f"Retries: {self.state.total_retries} (Lifetime: {self.state.lifetime_retries}) | Interventions: {self.state.total_human_interventions} (Lifetime: {self.state.lifetime_human_interventions})",
            "",
        ]

        for ts in self.spec.tasks:
            state = self.state.get_task(ts.id)
            if not state:
                continue
            icon = self._status_icon(state.status)
            retry_info = f" (retry {state.retries}/{ts.max_retries})" if state.retries > 0 else ""
            lines.append(f"  {icon} {ts.id}: {ts.title}{retry_info}")
            if state.review_feedback and state.status != TaskStatus.REVIEW_APPROVED:
                feedback = state.review_feedback[:120]
                lines.append(f"       {feedback}")
            if state.error_message:
                lines.append(f"       Error: {state.error_message[:120]}")
            if state.human_intervention_needed:
                lines.append(f"       HUMAN: {state.human_intervention_message[:120]}")

        if self.state.caps_hit:
            lines.append("")
            lines.append("CAPS HIT:")
            for cap, msg in self.state.caps_hit.items():
                lines.append(f"  - {cap}: {msg}")

        if self.state.needs_human():
            lines.append("")
            lines.append("ACTION REQUIRED:")
            for tid in self.state.needs_human():
                ts = self.state.get_task(tid)
                lines.append(f"  Task {tid}: {ts.human_intervention_message[:200]}")

        return "\n".join(lines)

    def _progress_bar(self, width: int = 30) -> str:
        total = len(self.spec.tasks)
        if total == 0:
            return "[]"
        done = sum(1 for ts in self.state.task_states.values() if ts.status == TaskStatus.REVIEW_APPROVED)
        filled = int(width * done / total)
        return "[" + "#" * filled + "-" * (width - filled) + "]"

    def _done_count(self) -> int:
        return sum(1 for ts in self.state.task_states.values() if ts.status == TaskStatus.REVIEW_APPROVED)

    def _status_icon(self, status: str) -> str:
        icons = {
            TaskStatus.REVIEW_APPROVED: "✅",
            TaskStatus.FAILED: "❌",
            TaskStatus.IN_PROGRESS: "🔄",
            TaskStatus.COMPLETED: "⏳",
            TaskStatus.REVIEWING: "🔍",
            TaskStatus.REVIEW_REJECTED: "↩️",
            TaskStatus.PENDING: "⬜",
            TaskStatus.RETRY: "🔁",
            TaskStatus.NEEDS_HUMAN: "🚨",
            TaskStatus.BLOCKED: "🚫",
            TaskStatus.SPEC_WRITING: "📝",
            TaskStatus.TESTS_WRITTEN: "🧪",
        }
        return icons.get(status, "❓")

    def _get_task_spec(self, task_id: str) -> TaskSpec:
        for t in self.spec.tasks:
            if t.id == task_id:
                return t
        raise ValueError(f"Task not in spec: {task_id}")

    def event_log_tail(self, n: int = 10) -> list[dict]:
        return [e.to_dict() for e in self.state.event_log[-n:]]
