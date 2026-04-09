"""Default mission caps config — GET+POST /api/config (default_caps section)."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from agentforce.server import state_io

DEFAULT_CAPS: dict = {
    "max_concurrent_workers": 2,
    "max_retries_per_task": 2,
    "max_wall_time_minutes": 60,
    "max_cost_usd": 0,
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


def load_caps() -> dict:
    path = _config_path()
    if not path.exists():
        _write_caps(DEFAULT_CAPS.copy())
        return DEFAULT_CAPS.copy()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        caps = data.get("default_caps", {})
        return {k: caps.get(k, v) for k, v in DEFAULT_CAPS.items()}
    except Exception:
        return DEFAULT_CAPS.copy()


def _write_caps(caps: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    existing["default_caps"] = caps
    tmp_fd, tmp_path_str = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(existing, fh, indent=2)
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
    caps_in = body.get("default_caps")
    if not isinstance(caps_in, dict):
        return 400, {"error": "default_caps is required"}
    merged = {k: caps_in.get(k, DEFAULT_CAPS[k]) for k in DEFAULT_CAPS}
    error = _validate(merged)
    if error:
        return 400, {"error": error}
    coerced = {
        "max_concurrent_workers": int(merged["max_concurrent_workers"]),
        "max_retries_per_task": int(merged["max_retries_per_task"]),
        "max_wall_time_minutes": int(merged["max_wall_time_minutes"]),
        "max_cost_usd": float(merged["max_cost_usd"]),
    }
    _write_caps(coerced)
    return 200, {"default_caps": coerced}
