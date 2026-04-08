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
import os
import sys
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
) -> tuple[bool, str, str, str | None]:
    """Dispatch to the selected connector. Returns (success, output, error, session_id)."""
    from agentforce.connectors import CONNECTORS
    if agent == "auto":
        agent = _detect_agent()
    connector = CONNECTORS.get(agent)
    if connector is None:
        raise ValueError(f"Unknown agent: {agent!r}. Available: {list(CONNECTORS)}")
    return connector(prompt, workdir, timeout, model, stream_path, variant, session_id)


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


_DEFAULT_MODEL = "opencode/nemotron-3-super-free"
_DEFAULT_VARIANT = "high"


def run_autonomous(
    mission_id: str,
    workdir: str = None,
    agent: str = "auto",
    model: str = None,
    variant: str = None,
    pool_size: int = 8,
):
    """Run a mission autonomously with a parallel supervisor loop.

    The supervisor ticks on a short interval, dispatches every available
    action (workers *and* reviewers) as concurrent threads, collects results
    as they finish, and feeds them back to the engine — all without blocking.

    Args:
        mission_id: The mission ID to run.
        workdir:    Override the working directory from the mission spec.
        agent:      ``"opencode"`` or ``"auto"`` (default).
        model:      Model string passed to the agent CLI (default: opencode/nemotron-3-super-free).
        variant:    Reasoning effort variant (default: high).
        pool_size:  Max concurrent agent threads (default 8). Actual task
                    parallelism is also governed by the mission's
                    ``max_concurrent_workers`` cap.
    """
    _ensure_pkg()
    from agentforce.core.engine import MissionEngine
    from agentforce.memory import Memory
    from agentforce.telemetry import TelemetryStore, TaskMetrics, MissionMetrics

    state_file = Path.home() / ".agentforce" / "state" / f"{mission_id}.json"
    if not state_file.exists():
        print(f"No mission state found: {mission_id}")
        sys.exit(1)

    resolved_agent = agent if agent != "auto" else _detect_agent()

    memory = Memory(Path.home() / ".agentforce" / "memory")
    engine = MissionEngine.load(state_file, memory)
    eff_model = model or _DEFAULT_MODEL
    eff_variant = variant or _DEFAULT_VARIANT

    engine.state.worker_agent = resolved_agent
    engine.state.worker_model = eff_model
    engine.state.caps_hit = {}
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
        effective_model = eff_model or getattr(action, "model", None)

        # Reuse session for the same task across worker retries (enables caching)
        session_id = session_ids.get(tid) if role == "worker" else None

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

        fut = executor.submit(
            _run_agent, action.context, _wdir, timeout,
            resolved_agent, effective_model, sp, eff_variant, session_id,
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
                success, output, error, returned_sid = fut.result()
            except Exception as exc:
                success, output, error, returned_sid = False, "", str(exc), None

            # Store session ID for reuse across worker retries
            if role == "worker" and returned_sid and tid not in session_ids:
                session_ids[tid] = returned_sid

            if role == "worker":
                now = datetime.now(timezone.utc).isoformat()
                tm = task_metrics.get(tid)
                if tm and tm.worker_started:
                    tm.worker_finished = now
                    tm.worker_duration_s = (
                        datetime.fromisoformat(now) - datetime.fromisoformat(tm.worker_started)
                    ).total_seconds()
                print(f"  ↓ [worker] task {tid}  success={success}  output={len(output)}B")
                if error and "timed out" not in error:
                    print(f"    error: {error[:200]}")
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

                if success and output:
                    review = _parse_reviewer_output(output)
                else:
                    review = {"approved": False, "feedback": f"Reviewer error: {error}", "score": 0}

                approved = review.get("approved", False)
                score = review.get("score", 0)
                feedback = review.get("feedback", "")
                blocking = review.get("blocking_issues", [])

                if tm:
                    tm.review_score = score
                    tm.review_approved = approved
                    tm.review_issues_count = len(blocking)

                print(f"  ↓ [reviewer] task {tid}  approved={approved}  score={score}")
                if not approved and feedback:
                    print(f"    feedback: {feedback[:200]}")
                engine.apply_reviewer_result(tid, approved, feedback, score, blocking)
                engine._save()

    tick = 0
    max_ticks = 500   # short ticks now — many more needed
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
                    print(f"    Auto-resolving.")
                    engine.apply_human_resolution(
                        action.task_id, "Auto-resolved: continuing with current implementation."
                    )
                    engine._save()

            if not actions and not in_flight:
                idle_ticks += 1
                if idle_ticks >= 3:
                    print(f"\n  No actions and nothing in flight — stopping.")
                    break
            else:
                idle_ticks = 0

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
        choices=["auto", "opencode"],
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
    a = p.parse_args()

    success = run_autonomous(
        a.mission_id, a.workdir,
        agent=a.agent, model=a.model, variant=a.variant, pool_size=a.pool_size,
    )
    sys.exit(0 if success else 1)
