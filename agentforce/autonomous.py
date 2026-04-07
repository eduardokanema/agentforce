"""Autonomous mission driver — runs entirely inside one delegated session.

Instead of the old pattern (an external orchestrator spawns workers, feeds
results back, spawns reviewers, feeds those back...), this module runs the
entire mission autonomously inside a single delegate_task call. It spawns
subprocesses (opencode run) for each worker and reviewer task and manages the
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
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


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


def _opencode_available() -> bool:
    """Check if opencode CLI is installed and configured."""
    try:
        r = subprocess.run(["opencode", "--version"], capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _run_opencode(prompt: str, workdir: str, timeout: int = 300) -> tuple[bool, str, str]:
    """Run opencode with a prompt and return (success, output, error)."""
    cmd = ["opencode", "run", prompt]
    env = os.environ.copy()
    # Pass through API keys
    for k in ["OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"]:
        if k in env:
            cmd_env = {**env}
            break
    else:
        cmd_env = env

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=workdir, env=cmd_env)
        output = r.stdout.strip()
        error = r.stderr.strip()
        success = r.returncode == 0 and "error" not in (r.stderr or "").lower()
        return success, output, error
    except subprocess.TimeoutExpired:
        return False, "", "opencode timed out"
    except Exception as e:
        return False, "", str(e)


def _parse_reviewer_output(output: str) -> dict:
    """Extract JSON from reviewer output."""
    for line in output.split("\n"):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                pass
        if line.startswith("```json"):
            try:
                block = output.split("```json", 1)[1].split("```", 1)[0].strip()
                return json.loads(block)
            except (json.JSONDecodeError, IndexError):
                pass
    # Fallback: try to find any JSON object
    import re
    match = re.search(r'(\{.*"approved".*\})', output, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return {"approved": False, "feedback": "Could not parse reviewer output", "score": 0}


def run_autonomous(mission_id: str, workdir: str = None):
    """Run a mission entirely autonomously using opencode subprocesses."""

    _ensure_pkg()
    from agentforce.core.engine import MissionEngine
    from agentforce.memory import Memory
    from agentforce.telemetry import TelemetryStore, TaskMetrics, MissionMetrics

    state_file = Path.home() / ".agentforce" / "state" / f"{mission_id}.json"
    if not state_file.exists():
        print(f"No mission state found: {mission_id}")
        sys.exit(1)

    memory = Memory(Path.home() / ".agentforce" / "memory")
    engine = MissionEngine.load(state_file, memory)
    tele_store = TelemetryStore()
    start = datetime.now(timezone.utc)

    print(f"\n=== Autonomous Mission Runner ===")
    print(f"Mission: {engine.spec.name} [{engine.state.mission_id}]")
    print(f"Tasks: {len(engine.spec.tasks)}")
    print(f"Workdir: {workdir or engine.state.working_dir}")
    print()

    # Clear caps so we can continue
    engine.state.caps_hit = {}
    engine._save()

    tick = 0
    max_ticks = 50
    task_metrics = {}

    while tick < max_ticks:
        tick += 1
        actions = engine.tick()

        if not actions:
            if engine.is_done():
                print(f"\nTick {tick}: Mission complete!")
                break
            if engine.is_failed():
                print(f"\nTick {tick}: Mission failed.")
                break
            # No actions but not done — check if there are pending tasks
            pending = engine.state.dispatchable_tasks()
            if pending:
                print(f"\nTick {tick}: No actions but {len(pending)} tasks pending.")
                print("This might mean all worker slots are full or waiting for deps.")
                if engine.state.in_progress_tasks():
                    print(f"  In progress: {[ts.task_id for ts in engine.state.in_progress_tasks()]}")
            # Check if we're stuck (no actions, no progress)
            time.sleep(1)
            continue

        print(f"\n--- Tick {tick}: {len(actions)} action(s) ---")
        for action in actions:
            role = getattr(action, "role", "?")
            tid = action.task_id
            print(f"  [{role}] Task {tid}")

            if hasattr(action, "context"):
                # Worker action — spawn opencode
                if role == "worker":
                    print(f"    Spawning opencode worker for task {tid}...")
                    task_metrics[tid] = TaskMetrics(
                        task_id=tid,
                        task_title=engine._task_spec(tid).title,
                        mission_id=engine.state.mission_id,
                        worker_started=datetime.now(timezone.utc).isoformat(),
                    )
                    task_metrics[tid].worker_attempts += 1

                    success, output, error = _run_opencode(
                        prompt=action.context,
                        workdir=workdir or engine.state.working_dir,
                        timeout=getattr(action, "timeout", 300),
                    )
                    task_metrics[tid].worker_finished = datetime.now(timezone.utc).isoformat()
                    task_metrics[tid].worker_duration_s = (
                        datetime.fromisoformat(task_metrics[tid].worker_finished)
                        - datetime.fromisoformat(task_metrics[tid].worker_started)
                    ).total_seconds()

                    print(f"    Worker result: success={success}, output_len={len(output)}")
                    if error and "timed out" not in error:
                        print(f"    Error: {error[:200]}")

                    engine.apply_worker_result(tid, success, output, error)
                    engine._save()

                # Reviewer action — spawn opencode for review
                elif role == "reviewer":
                    print(f"    Spawning opencode reviewer for task {tid}...")
                    task_metrics.setdefault(tid, TaskMetrics(
                        task_id=tid,
                        task_title=engine._task_spec(tid).title,
                        mission_id=engine.state.mission_id,
                    ))
                    task_metrics[tid].reviewer_started = datetime.now(timezone.utc).isoformat()
                    task_metrics[tid].review_attempts += 1

                    success, output, error = _run_opencode(
                        prompt=action.context,
                        workdir=workdir or engine.state.working_dir,
                        timeout=getattr(action, "timeout", 120),
                    )
                    task_metrics[tid].reviewer_finished = datetime.now(timezone.utc).isoformat()
                    task_metrics[tid].reviewer_duration_s = (
                        datetime.fromisoformat(task_metrics[tid].reviewer_finished)
                        - datetime.fromisoformat(task_metrics[tid].reviewer_started)
                    ).total_seconds()

                    if success and output:
                        review = _parse_reviewer_output(output)
                    else:
                        review = {"approved": False, "feedback": f"Reviewer error: {error}", "score": 0}

                    approved = review.get("approved", False)
                    score = review.get("score", 0)
                    feedback = review.get("feedback", "")
                    blocking = review.get("blocking_issues", [])

                    task_metrics[tid].review_score = score
                    task_metrics[tid].review_approved = approved
                    task_metrics[tid].review_issues_count = len(blocking)

                    print(f"    Review result: approved={approved}, score={score}")
                    if not approved:
                        print(f"    Feedback: {feedback[:200]}")

                    engine.apply_reviewer_result(tid, approved, feedback, score, blocking)
                    engine._save()

                # Human intervention — auto-resolve or mark as failed
                elif role == "human" or hasattr(action, "message"):
                    print(f"    Human intervention needed: {getattr(action, 'message', 'blocked')}")
                    print(f"    Auto-resolving: continuing with best effort")
                    engine.apply_human_resolution(tid, "Auto-resolved: continuing with current implementation.")
                    engine._save()

        # Brief pause between ticks
        time.sleep(0.5)

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
    if len(sys.argv) < 2:
        print(f"Usage: python3 -m agentforce.autonomous <mission_id> [--workdir PATH]")
        sys.exit(1)

    mid = sys.argv[1]
    workdir = None
    if len(sys.argv) > 2 and sys.argv[2] == "--workdir":
        workdir = sys.argv[3]

    success = run_autonomous(mid, workdir)
    sys.exit(0 if success else 1)
