"""CLI — manage and run missions."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure agentforce is importable when running from source
_pkg_root = Path(__file__).resolve().parents[2]
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

AGENTFORCE_HOME = Path(os.path.expanduser("~/.agentforce"))
STATE_DIR = AGENTFORCE_HOME / "state"
MEMORY_DIR = AGENTFORCE_HOME / "memory"


def _ensure_dirs():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def _find_state(mission_id: str) -> Path | None:
    if not STATE_DIR.exists():
        return None
    state_files = list(STATE_DIR.glob("*.json"))
    for sf in state_files:
        if sf.stem == mission_id:
            return sf
    matches = [sf for sf in state_files if sf.stem.startswith(mission_id)]
    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        print(f"Ambiguous mission ID: {mission_id}. Matches:", file=sys.stderr)
        for m in matches:
            print(f"  {m.stem}", file=sys.stderr)
        sys.exit(1)
    return None


def _memory():
    _ensure_dirs()
    from agentforce.memory import Memory
    return Memory(MEMORY_DIR)


def cmd_start(args):
    """Start a new mission."""
    spec_path = Path(args.spec)
    if not spec_path.exists():
        print(f"Error: Spec file not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    from agentforce.core.spec import MissionSpec

    if spec_path.suffix in (".yaml", ".yml"):
        try:
            import yaml
            spec = MissionSpec.load_yaml(spec_path)
        except ImportError:
            print("Warning: PyYAML not available, trying JSON parse…", file=sys.stderr)
            with open(spec_path) as f:
                spec = MissionSpec.from_dict(json.load(f))
    elif spec_path.suffix == ".json":
        spec = MissionSpec.load_json(spec_path)
    else:
        print(f"Error: Unknown spec format: {spec_path.suffix}", file=sys.stderr)
        sys.exit(1)

    issues = spec.validate()
    if issues:
        print("Spec validation errors:", file=sys.stderr)
        for i in issues:
            print(f"  - {i}", file=sys.stderr)
        sys.exit(1)
    print("Spec validated OK")

    from agentforce.core.engine import MissionEngine

    memory = _memory()
    workdir = args.workdir or str(Path(spec.working_dir or f"./missions-{spec.short_id()}").resolve())
    Path(workdir).mkdir(parents=True, exist_ok=True)
    print(f"Working directory: {workdir}")

    engine = MissionEngine.create(
        spec=spec, state_dir=STATE_DIR, memory=memory,
        mission_id=args.id, worker_model=args.worker_model,
        reviewer_model=args.reviewer_model,
    )
    engine.state.working_dir = workdir
    engine._save()

    mid = engine.state.mission_id
    print(f"\nMission started: {spec.name}")
    print(f"  ID: {mid}")
    print(f"  Tasks: {len(spec.tasks)}")
    print(f"  Caps: workers={spec.caps.max_concurrent_workers}, retries={spec.caps.max_retries_per_task}/task, wall={spec.caps.max_wall_time_minutes}m")
    print(f"\nTo run autonomously:")
    print(f"  python3 -m agentforce.autonomous {mid}")
    print(f"  python3 -m agentforce.autonomous {mid} --agent opencode --model <model-id>")
    print(f"  python3 -m agentforce.autonomous {mid} --agent claude --model claude-sonnet-4-6")


def cmd_status(args):
    from agentforce.core.state import MissionState
    sf = _find_state(args.id)
    if not sf:
        print(f"No mission found: {args.id}", file=sys.stderr)
        sys.exit(1)
    state = MissionState.load(sf)
    cap = state.check_caps()
    if cap:
        print(f"CAP HIT: {cap}")
    print(state.summary())
    if state.needs_human():
        print(f"\nHUMAN INTERVENTION REQUIRED:")
        for tid in state.needs_human():
            ts = state.get_task(tid)
            print(f"  [{tid}] {ts.human_intervention_message}")
    if args.json:
        print(json.dumps(state.to_dict(), indent=2))


def cmd_list(args):
    _ensure_dirs()
    if not STATE_DIR.exists():
        print("No missions found.")
        return
    from agentforce.core.state import MissionState
    files = sorted(STATE_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        print("No missions found.")
        return
    print(f"{'ID':<10} {'Name':<35} {'Done':<8} {'Status'}")
    print("-" * 80)
    for sf in files:
        try:
            s = MissionState.load(sf)
            done = sum(1 for t in s.task_states.values() if t.status == "review_approved")
            total = len(s.task_states)
            if s.is_done():
                status = "COMPLETE"
            elif s.is_failed():
                status = "FAILED"
            elif s.needs_human():
                status = "NEEDS HUMAN"
            elif s.caps_hit:
                status = "CAP HIT"
            else:
                active = sum(1 for t in s.task_states.values() if t.status == "in_progress")
                status = f"ACTIVE ({active})"
            print(f"{s.mission_id:<10} {s.spec.name:<35} {done}/{total:<5} {status}")
        except Exception:
            print(f"{sf.stem:<10} [error]")


def cmd_resolve(args):
    from agentforce.core.engine import MissionEngine
    sf = _find_state(args.id)
    if not sf:
        print(f"No mission found: {args.id}", file=sys.stderr)
        sys.exit(1)
    engine = MissionEngine.load(sf, _memory())
    engine.apply_human_resolution(args.task_id, args.message)
    engine._save()
    print(f"Resolved {args.task_id} -> {engine.state.get_task(args.task_id).status}")


def cmd_fail(args):
    from agentforce.core.engine import MissionEngine
    sf = _find_state(args.id)
    if not sf:
        print(f"No mission found: {args.id}", file=sys.stderr)
        sys.exit(1)
    engine = MissionEngine.load(sf, _memory())
    engine.resolve_as_failed(args.task_id)
    engine._save()
    print(f"Failed {args.task_id}")


def cmd_report(args):
    from agentforce.core.engine import MissionEngine
    sf = _find_state(args.id)
    if not sf:
        print(f"No mission found: {args.id}", file=sys.stderr)
        sys.exit(1)
    engine = MissionEngine.load(sf, _memory())
    print(engine.report())
    if args.events:
        print("\nRECENT EVENTS:")
        for e in engine.event_log_tail(args.events):
            ts = e.get("timestamp", "?")[:19]
            tid = e.get("task_id", "")
            tpfx = f" [{tid}]" if tid else ""
            print(f"  {ts} {e['event_type']}{tpfx}: {e['details']}")


def cmd_kill(args):
    from agentforce.core.state import MissionState
    sf = _find_state(args.id)
    if not sf:
        print(f"No mission found: {args.id}", file=sys.stderr)
        sys.exit(1)
    s = MissionState.load(sf)
    s.completed_at = datetime.now(timezone.utc).isoformat()
    s.log_event("mission_killed", details="Killed by user")
    s.save(sf)
    print(f"Killed {s.mission_id}")


def cmd_cat(args):
    sf = _find_state(args.id)
    if not sf:
        print(f"No mission found: {args.id}", file=sys.stderr)
        sys.exit(1)
    with open(sf) as f:
        print(f.read())


def cmd_metrics(args):
    """Show aggregated telemetry across missions."""
    from agentforce.telemetry import TelemetryStore
    store = TelemetryStore()
    missions = store.list_missions()
    if not missions:
        print("No telemetry data yet.")
        return
    if args.mission:
        m = store.load_mission(args.mission)
        if m:
            print(json.dumps(m.to_dict(), indent=2))
        else:
            print(f"No metrics for mission {args.mission}")
        return
    print(f"{'ID':<10} {'Name':<30} {'Tasks':<6} {'Duration':<10} {'Score':<6} {'Retries':<8} {'First-pass':<10}")
    print("-" * 80)
    for m in missions:
        dur = f"{m['total_duration_s']:.0f}s" if m.get('total_duration_s') else "?"
        score = f"{m.get('avg_review_score', 0):.1f}"
        print(f"{m['mission_id']:<10} {m['mission_name']:<30} {m['total_tasks']:<6} {dur:<10} {score:<6} {m.get('total_retries', 0):<8} {m.get('approved_on_first_try', 0)}/{m['total_tasks']}")


def cmd_serve(args):
    """Start the mission dashboard HTTP server."""
    from agentforce.server import serve
    serve(port=args.port)


def main():
    parser = argparse.ArgumentParser(prog="mission", description="AgentForce CLI")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("start"); p.add_argument("spec"); p.add_argument("--id"); p.add_argument("--workdir"); p.add_argument("--worker-model"); p.add_argument("--reviewer-model")
    p = sub.add_parser("status"); p.add_argument("id"); p.add_argument("--json", action="store_true")
    sub.add_parser("list")
    p = sub.add_parser("resolve"); p.add_argument("id"); p.add_argument("task_id"); p.add_argument("message")
    p = sub.add_parser("fail"); p.add_argument("id"); p.add_argument("task_id")
    p = sub.add_parser("report"); p.add_argument("id"); p.add_argument("--events", type=int, default=0)
    p = sub.add_parser("kill"); p.add_argument("id")
    sub.add_parser("cat").add_argument("id")
    p = sub.add_parser("metrics"); p.add_argument("--mission", help="Show single mission metrics")
    p = sub.add_parser("serve", help="start mission dashboard web server"); p.add_argument("--port", type=int, default=8080, help="port to listen on (default: 8080)")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    cmds = {"start": cmd_start, "status": cmd_status, "list": cmd_list,
            "resolve": cmd_resolve, "fail": cmd_fail, "report": cmd_report,
            "kill": cmd_kill, "cat": cmd_cat, "metrics": cmd_metrics,
            "serve": cmd_serve}
    cmds[args.command](args)


if __name__ == "__main__":
    main()
