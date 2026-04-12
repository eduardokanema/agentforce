"""Dashboard config — GET+POST /api/config persisted settings."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from agentforce.server import state_io

DEFAULT_CAPS: dict = {
    "max_concurrent_workers": 2,
    "max_retries_per_task": 3,
    "max_wall_time_minutes": 60,
    "max_cost_usd": 0,
}

DEFAULT_FILESYSTEM_SETTINGS: dict = {
    "default_start_path": "~/Projects",
}

# field → (coerce_fn, min_inclusive, max_inclusive_or_None)
_RULES: dict[str, tuple] = {
    "max_concurrent_workers": (int, 1, 8),
    "max_retries_per_task": (int, 1, 5),
    "max_wall_time_minutes": (int, 10, 480),
    "max_cost_usd": (float, 0, None),
}


def _config_path() -> Path:
    return state_io.get_agentforce_home() / "config.json"


def _load_dashboard_config() -> dict:
    path = _config_path()
    if not path.exists():
        data = {
            "default_caps": DEFAULT_CAPS.copy(),
            "filesystem": DEFAULT_FILESYSTEM_SETTINGS.copy(),
        }
        _write_dashboard_config(data)
        return data
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_caps() -> dict:
    data = _load_dashboard_config()
    caps = data.get("default_caps", {})
    return {k: caps.get(k, v) for k, v in DEFAULT_CAPS.items()}


def load_filesystem_settings() -> dict:
    data = _load_dashboard_config()
    filesystem = data.get("filesystem", {})
    return {k: filesystem.get(k, v) for k, v in DEFAULT_FILESYSTEM_SETTINGS.items()}


def _write_dashboard_config(data: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path_str = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path_str, path)
    except Exception:
        try:
            os.unlink(tmp_path_str)
        except OSError:
            pass
        raise


def _validate(caps: dict) -> str | None:
    for field, (typ, lo, hi) in _RULES.items():
        if field not in caps:
            continue
        try:
            val = typ(caps[field])
        except (TypeError, ValueError):
            return f"{field} out of range"
        if lo is not None and val < lo:
            return f"{field} out of range"
        if hi is not None and val > hi:
            return f"{field} out of range"
    return None


def post(handler, parts: list[str], query: dict):
    body = handler._read_json_body()
    if not isinstance(body, dict):
        return 400, {"error": "invalid config payload"}

    current_caps = load_caps()
    current_filesystem = load_filesystem_settings()

    caps_in = body.get("default_caps")
    if caps_in is None:
        coerced_caps = current_caps
    else:
        if not isinstance(caps_in, dict):
            return 400, {"error": "default_caps must be an object"}
        merged = {k: caps_in.get(k, current_caps[k]) for k in DEFAULT_CAPS}
        error = _validate(merged)
        if error:
            return 400, {"error": error}
        coerced_caps = {
            "max_concurrent_workers": int(merged["max_concurrent_workers"]),
            "max_retries_per_task": int(merged["max_retries_per_task"]),
            "max_wall_time_minutes": int(merged["max_wall_time_minutes"]),
            "max_cost_usd": float(merged["max_cost_usd"]),
        }

    filesystem_in = body.get("filesystem")
    if filesystem_in is None:
        coerced_filesystem = current_filesystem
    else:
        if not isinstance(filesystem_in, dict):
            return 400, {"error": "filesystem must be an object"}
        raw_default_start_path = filesystem_in.get("default_start_path", current_filesystem["default_start_path"])
        if raw_default_start_path is None:
            raw_default_start_path = ""
        if not isinstance(raw_default_start_path, str):
            return 400, {"error": "filesystem.default_start_path must be a string"}
        coerced_filesystem = {
            "default_start_path": raw_default_start_path.strip(),
        }

    _write_dashboard_config({
        "default_caps": coerced_caps,
        "filesystem": coerced_filesystem,
    })
    return 200, {
        "default_caps": coerced_caps,
        "filesystem": coerced_filesystem,
    }
