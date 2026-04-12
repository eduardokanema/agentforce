#!/usr/bin/env python3
"""Replay an AgentForce plan-run retry path against temp-copied state."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agentforce.core.token_event import TokenEvent
from agentforce.server import planner_adapter
from agentforce.server.plan_drafts import PlanDraftStore, redact_persisted_content
from agentforce.server.plan_runs import PlanRunRecord, PlanRunStore
from agentforce.server.planning_runtime import create_plan_run_for_draft, run_plan_run

EMPTY_VALIDATION = {
    "issues": [],
    "warnings": [],
    "structured_issues": [],
    "blocking_issues": [],
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replay an AgentForce plan-run retry path against temp-copied state. "
            "This command never mutates the real state root."
        )
    )
    parser.add_argument("--draft-id", required=True, help="Draft ID to replay.")
    parser.add_argument(
        "--source-run-id",
        help="Optional source run ID. Defaults to the most recent run for the draft in the source state root.",
    )
    parser.add_argument(
        "--state-root",
        default=str(Path("~/.agentforce").expanduser()),
        help="Source AgentForce state root to read from. Default: ~/.agentforce",
    )
    parser.add_argument(
        "--planner-output-file",
        help="Optional file containing raw planner output text to stub into the replay.",
    )
    parser.add_argument(
        "--critic-output-file",
        help="Optional file containing raw critic output text to stub into the replay.",
    )
    parser.add_argument(
        "--stub-empty-validation",
        action="store_true",
        help="Stub mission-plan validation to an empty result. Use when isolating planner or retry-path behavior.",
    )
    return parser.parse_args()


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _resolve_source_run_id(plan_store: PlanRunStore, draft_id: str, requested: str | None) -> str | None:
    if requested:
        return requested
    runs = plan_store.list_runs_for_draft(draft_id)
    return runs[0].id if runs else None


def _copy_minimal_state(source_root: Path, temp_root: Path, draft_id: str, source_run_id: str | None) -> None:
    draft_path = source_root / "drafts" / f"{draft_id}.json"
    if not draft_path.exists():
        raise FileNotFoundError(f"Draft {draft_id!r} not found at {draft_path}")
    _copy_file(draft_path, temp_root / "drafts" / draft_path.name)

    if source_run_id:
        run_path = source_root / "plans" / "runs" / f"{source_run_id}.json"
        if not run_path.exists():
            raise FileNotFoundError(f"Run {source_run_id!r} not found at {run_path}")
        _copy_file(run_path, temp_root / "plans" / "runs" / run_path.name)


def _load_text(path: str | None) -> str | None:
    if not path:
        return None
    return Path(path).expanduser().read_text(encoding="utf-8")


def _summary(run: PlanRunRecord | None) -> dict[str, object]:
    if run is None:
        summary = {
            "plan_run_id": None,
            "status": "missing",
            "current_step": None,
            "error_message": "Run record was not created",
            "result_version_id": None,
            "steps": [],
        }
        return redact_persisted_content(summary)
    summary = {
        "plan_run_id": run.id,
        "status": run.status,
        "current_step": run.current_step,
        "error_message": run.error_message,
        "result_version_id": run.result_version_id,
        "steps": [
            {
                "name": step.name,
                "status": step.status,
                "message": step.message,
            }
            for step in run.steps
        ],
    }
    return redact_persisted_content(summary)


def _planner_stub(text: str):
    return lambda *args, **kwargs: text


def main() -> int:
    args = _parse_args()
    source_root = Path(args.state_root).expanduser()
    source_plan_store = PlanRunStore(source_root / "plans")
    source_run_id = _resolve_source_run_id(source_plan_store, args.draft_id, args.source_run_id)
    planner_output = _load_text(args.planner_output_file)
    critic_output = _load_text(args.critic_output_file)

    with tempfile.TemporaryDirectory(prefix="agentforce-plan-replay-") as temp_dir:
        temp_root = Path(temp_dir)
        _copy_minimal_state(source_root, temp_root, args.draft_id, source_run_id)

        draft_store = PlanDraftStore(temp_root / "drafts")
        plan_store = PlanRunStore(temp_root / "plans")
        draft = draft_store.load(args.draft_id)
        if draft is None:
            raise RuntimeError(f"Draft {args.draft_id!r} could not be loaded from temp state")

        trigger_message = (
            f"Retry of run {source_run_id}"
            if source_run_id
            else f"Replay retry for draft {args.draft_id}"
        )

        with ExitStack() as stack:
            stack.enter_context(patch("agentforce.server.planning_runtime._draft_store", return_value=draft_store))
            stack.enter_context(patch("agentforce.server.planning_runtime._plan_store", return_value=plan_store))
            stack.enter_context(patch("agentforce.server.planning_runtime.ws.broadcast", new=lambda *_a, **_k: None))

            if planner_output is not None:
                stack.enter_context(patch.object(planner_adapter, "_codex_cli_completion", new=_planner_stub(planner_output)))
                stack.enter_context(patch.object(planner_adapter, "_claude_cli_completion", new=_planner_stub(planner_output)))
                stack.enter_context(patch.object(planner_adapter, "_gemini_cli_completion", new=_planner_stub(planner_output)))
                stack.enter_context(patch.object(planner_adapter, "_openrouter_completion", new=_planner_stub(planner_output)))
                stack.enter_context(patch.object(planner_adapter, "_anthropic_completion", new=_planner_stub(planner_output)))

            if critic_output is not None:
                stack.enter_context(
                    patch(
                        "agentforce.server.planning_runtime._invoke_profile",
                        return_value=(critic_output, TokenEvent(0, 0, 0.0)),
                    )
                )

            if args.stub_empty_validation:
                stack.enter_context(
                    patch(
                        "agentforce.server.planning_runtime._mission_plan_validation",
                        return_value=EMPTY_VALIDATION,
                    )
                )

            run = create_plan_run_for_draft(
                draft,
                trigger_kind="retry",
                trigger_message=trigger_message,
            )

            try:
                run_plan_run(run.id)
            except Exception:
                pass

        latest = plan_store.load_run(run.id)
        print(json.dumps(_summary(latest), indent=2))
        return 0 if latest is not None and latest.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
