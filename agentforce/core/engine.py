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

from .state import MissionState, TaskState
from .spec import MissionSpec, TaskSpec, TaskStatus

logger = logging.getLogger("agentforce.engine")


# ── Delegation descriptors ──

@dataclass
class WorkerDelegation:
    """Descriptor for a worker agent to dispatch."""
    task_id: str
    role: str = "worker"
    goal: str = ""
    context: str = ""
    toolsets: list[str] = field(default_factory=lambda: ["terminal", "file"])
    model: Optional[str] = None
    timeout: int = 300


@dataclass
class ReviewerDelegation:
    """Descriptor for a reviewer agent to dispatch."""
    task_id: str
    role: str = "reviewer"
    goal: str = ""
    context: str = ""
    toolsets: list[str] = field(default_factory=lambda: ["file"])
    model: Optional[str] = None
    timeout: int = 120


@dataclass
class HumanIntervention:
    """When the engine needs human attention."""
    task_id: str
    message: str
    suggestions: list[str] = field(default_factory=list)


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
        self.spec = spec
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.memory = memory
        self.worker_model = worker_model
        self.reviewer_model = reviewer_model
        
        mid = mission_id or spec.short_id()
        self.state = MissionState(mission_id=mid, spec=spec)
        self.state.working_dir = str(Path(spec.working_dir or f"./missions-{mid}").resolve())
        
        # Initialize task states
        for ts in spec.tasks:
            self.state.task_states[ts.id] = TaskState(
                task_id=ts.id,
                spec_summary=f"{ts.title}"[:200],
            )
        
        self.state.log_event("mission_started", details=f"Started mission: {spec.name}")
        self._state_file = self.state_dir / f"{mid}.json"
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
        return engine

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

        # Check caps
        cap_hit = self._check_caps()
        if cap_hit:
            self.state.log_event("mission_failed", details=cap_hit)
            self._save()
            return actions  # Stop all activity

        # Human interventions first — if we're past the limit, fail the mission
        if self.state.interventions_exhausted() and self.state.needs_human():
            self.state.log_event("mission_failed", details="Intervention limit exhausted")
            self._save()
            return actions

        # Surface any human interventions
        for tid in self.state.needs_human():
            ts = self.state.get_task(tid)
            actions.append(HumanIntervention(
                task_id=tid,
                message=ts.human_intervention_message or f"Task {tid} requires human attention",
            ))

        # Try to dispatch workers for pending tasks
        if self.state.workers_available():
            dispatchable = self.state.dispatchable_tasks()
            for tid in dispatchable:
                if self.state.worker_count() >= self.state.caps.max_concurrent_workers:
                    break
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
        mem_context = self.memory.agent_context(self.state.mission_id, task_id)
        
        prompt = task_spec.generate_worker_prompt()
        if mem_context:
            prompt += f"\n\nMEMORY CONTEXT:\n{mem_context}"

        if ts.retries > 0:
            prompt += f"\n\nPREVIOUS ATTEMPT FAILED (attempt {ts.retries + 1} of {task_spec.max_retries + 1})."
            if ts.review_feedback:
                prompt += f"\nReviewer feedback: {ts.review_feedback}"
            if ts.error_message:
                prompt += f"\nPrevious error: {ts.error_message}"

        self.state.log_event("task_dispatched", task_id, f"Worker dispatched for {task_spec.title}")
        logger.info("Dispatching worker: %s - %s", task_id, task_spec.title)

        return WorkerDelegation(
            task_id=task_id,
            goal=f"Complete task {task_id}: {task_spec.title}",
            context=prompt,
            model=self.worker_model,
            timeout=min(600, self.state.caps.max_wall_time_minutes * 60),
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
        mem_context = self.memory.agent_context(self.state.mission_id, task_id)
        
        prompt = task_spec.generate_reviewer_prompt(
            worker_output=ts.worker_output,
            mission_name=self.state.spec.name,
            dod="; ".join(self.state.spec.definition_of_done),
            project_memory=mem_context,
        )

        self.state.log_event("review_started", task_id, f"Review started for {task_spec.title}")
        logger.info("Dispatching reviewer: %s", task_id)

        return ReviewerDelegation(
            task_id=task_id,
            goal=f"Review task {task_id}: {task_spec.title}",
            context=prompt,
            model=self.reviewer_model,
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

        if success:
            ts.worker_output = output
            ts.status = TaskStatus.COMPLETED
            self.state.log_event("task_completed", task_id, f"Worker completed {task_spec.title}")
            logger.info("Worker completed: %s", task_id)
        else:
            ts.error_message = error or "Worker reported failure"
            ts.retries += 1
            self.state.total_retries += 1

            # Check if we can retry
            if ts.retries >= task_spec.max_retries or self.state.total_retries >= self.state.caps.max_retries_global:
                ts.status = TaskStatus.FAILED
                self.state.log_event("task_failed", task_id, ts.error_message)
                logger.warning("Task failed permanently: %s", task_id)
            else:
                ts.status = TaskStatus.RETRY
                self.state.log_event("task_retry", task_id, f"Retry {ts.retries}/{task_spec.max_retries}")
                logger.info("Retrying task: %s (attempt %d)", task_id, ts.retries + 1)

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
        ts.blocking_issues = blocking_issues or []

        if approved:
            ts.status = TaskStatus.REVIEW_APPROVED
            ts.completed_at = datetime.now(timezone.utc).isoformat()
            self.memory.task_clear(task_id)  # Clean ephemeral memory
            self.state.log_event("review_approved", task_id, feedback)
            logger.info("Task review approved: %s", task_id)

            # Update project memory with lessons learned
            if feedback and len(feedback) < 500:
                self.memory.project_set(
                    self.state.mission_id,
                    f"task_{task_id}_outcome",
                    feedback[:500],
                    category="fact"
                )
        else:
            ts.retries += 1
            self.state.total_retries += 1

            # Check if issues need human intervention
            if blocking_issues and len(blocking_issues) > 0:
                # If blocking issues are about spec ambiguity, flag for human
                ts.human_intervention_needed = True
                ts.human_intervention_message = (
                    f"Reviewer blocked on task {task_id}: "
                    f"{'; '.join(blocking_issues)}\n"
                    f"Feedback: {feedback}"
                )
                ts.status = TaskStatus.NEEDS_HUMAN
                self.state.total_human_interventions += 1
                self.state.log_event("human_intervention", task_id, ts.human_intervention_message)
                logger.warning("Human intervention needed: %s", task_id)
            elif ts.retries >= task_spec.max_retries or self.state.total_retries >= self.state.caps.max_retries_global:
                ts.status = TaskStatus.FAILED
                self.state.log_event("task_failed", task_id, f"Max retries exceeded: {feedback}")
                logger.warning("Task failed after retries: %s", task_id)
            else:
                ts.status = TaskStatus.RETRY
                self.state.log_event("review_rejected", task_id, f"Retry {ts.retries}/{task_spec.max_retries}: {feedback}")
                logger.info("Task rejected, will retry: %s (score: %d)", task_id, score)

        self._save()

    def apply_human_resolution(self, task_id: str, resolution: str):
        """Apply human intervention for a blocked task."""
        ts = self.state.get_task(task_id)
        if not ts:
            raise ValueError(f"Unknown task: {task_id}")
        
        if not ts.needs_human_attention():
            raise ValueError(f"Task {task_id} doesn't need human attention")

        ts.human_intervention_needed = False
        ts.human_intervention_message = ""
        ts.status = TaskStatus.RETRY
        ts.review_feedback = f"HUMAN RESOLUTION: {resolution}"
        ts.bump()
        
        self.state.log_event("human_resolved", task_id, resolution)
        logger.info("Human resolved task: %s", task_id)
        self._save()

    def resolve_as_failed(self, task_id: str):
        """Mark a human-blocked task as permanently failed."""
        ts = self.state.get_task(task_id)
        if not ts:
            raise ValueError(f"Unknown task: {task_id}")
        
        ts.status = TaskStatus.FAILED
        ts.human_intervention_needed = False
        ts.bump()
        
        self.state.log_event("task_failed", task_id, "Marked as failed by human")
        self._save()

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
            f"Retries: {self.state.total_retries} | Interventions: {self.state.total_human_interventions}",
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
