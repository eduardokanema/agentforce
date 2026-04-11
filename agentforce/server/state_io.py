"""Shared server state I/O helpers for AgentForce dashboard."""
from __future__ import annotations

import json as _jsonlib
import os
from pathlib import Path
from typing import Any

from agentforce.core.event_bus import EVENT_BUS

from . import ws

_DEFAULT_AGENTFORCE_HOME = Path(os.path.expanduser("~/.agentforce"))
AGENTFORCE_HOME = _DEFAULT_AGENTFORCE_HOME
STATE_DIR = AGENTFORCE_HOME / "state"
_DEFAULT_STATE_DIR = STATE_DIR
_STATE_DIR_OVERRIDE: Path | None = None


def _handler_module():
    try:
        from . import handler as handler_mod

        return handler_mod
    except Exception:
        return None


def get_agentforce_home() -> Path:
    if AGENTFORCE_HOME != _DEFAULT_AGENTFORCE_HOME:
        return AGENTFORCE_HOME
    handler_mod = _handler_module()
    if handler_mod is not None and hasattr(handler_mod, "AGENTFORCE_HOME"):
        return Path(getattr(handler_mod, "AGENTFORCE_HOME"))
    return AGENTFORCE_HOME


def get_state_dir() -> Path:
    if _STATE_DIR_OVERRIDE is not None:
        return _STATE_DIR_OVERRIDE
    handler_mod = _handler_module()
    if handler_mod is not None:
        handler_cls = getattr(handler_mod, "DashboardHandler", None)
        handler_config = getattr(handler_cls, "config", None) if handler_cls is not None else None
        if handler_config is not None:
            handler_state_dir = Path(handler_config.state_dir)
            if handler_state_dir != _DEFAULT_STATE_DIR:
                return handler_state_dir
    return STATE_DIR


def set_state_dir(state_dir: Path | str | None) -> None:
    global _STATE_DIR_OVERRIDE
    _STATE_DIR_OVERRIDE = Path(state_dir) if state_dir is not None else None


def _connectors_path() -> Path:
    return get_agentforce_home() / "connectors.json"


def _load_connectors_metadata() -> dict[str, dict[str, Any]]:
    path = _connectors_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("{}", encoding="utf-8")
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = _jsonlib.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_connectors_metadata(data: dict[str, dict[str, Any]]) -> None:
    path = _connectors_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        _jsonlib.dump(data, fh, indent=2)


def _providers_path() -> Path:
    return get_agentforce_home() / "providers.json"


def _load_providers_metadata() -> dict[str, dict]:
    path = _providers_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = _jsonlib.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_providers_metadata(data: dict) -> None:
    path = _providers_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        _jsonlib.dump(data, fh, indent=2)


def _flags_path() -> Path:
    return get_agentforce_home() / "mission_flags.json"


def _load_mission_flags() -> dict[str, dict]:
    path = _flags_path()
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = _jsonlib.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_mission_flags(flags: dict[str, dict]) -> None:
    path = _flags_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        _jsonlib.dump(flags, fh, indent=2)


def _task_status_value(task_state) -> str:
    """Extract status value from TaskState, handling both enum and string values."""
    status = getattr(task_state.status, "value", task_state.status)
    return str(status)


def _state_path(mission_id: str) -> Path:
    return get_state_dir() / f"{mission_id}.json"


def _load_state(mission_id: str, state_dir: Path | None = None):
    """Load a mission state from disk by mission_id."""
    from agentforce.core.state import MissionState

    state_root = Path(state_dir) if state_dir is not None else get_state_dir()
    if not state_root.exists():
        return None
    for sf in state_root.glob("*.json"):
        if sf.stem == mission_id or sf.stem.startswith(mission_id):
            try:
                return MissionState.load(sf)
            except Exception:
                return None
    return None


def _load_all_missions(state_dir: Path | None = None, include_archived: bool = False) -> list:
    """Load all mission states from the state directory."""
    from agentforce.core.state import MissionState

    state_root = Path(state_dir) if state_dir is not None else get_state_dir()
    if not state_root.exists():
        return []

    flags = _load_mission_flags()
    missions = []
    for sf in sorted(state_root.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            mission = MissionState.load(sf)
            mf = flags.get(mission.mission_id, {})
            if mf.get("deleted"):
                continue
            if mf.get("archived") and not include_archived:
                continue
            missions.append(mission)
        except Exception:
            continue
    return missions


def _all_mission_summaries() -> list[dict]:
    from .plan_drafts import PlanDraftStore
    drafts = PlanDraftStore().list_all(include_terminal=False)
    draft_summaries = [
        {
            "mission_id": d.id,
            "name": d.name,
            "status": d.status,
            "is_draft": True,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in drafts
    ]

    missions = _load_all_missions()
    mission_summaries = []
    for mission in missions:
        summary = mission.to_summary_dict()
        summary["is_draft"] = False
        mission_summaries.append(summary)

    return mission_summaries + draft_summaries


def _broadcast_mission_refresh(state) -> None:
    """Broadcast mission state update to all connected WebSocket clients."""
    try:
        EVENT_BUS.publish(
            "mission.snapshot",
            {"mission_id": state.mission_id, "state": state.to_dict()},
        )
        EVENT_BUS.publish(
            "mission.list_snapshot",
            {"missions": _all_mission_summaries()},
        )
    except Exception:
        pass


def _broadcast_mission_list_refresh() -> None:
    try:
        EVENT_BUS.publish(
            "mission.list_snapshot",
            {"missions": _all_mission_summaries()},
        )
    except Exception:
        pass
