"""Filesystem and config API route."""
from __future__ import annotations

from pathlib import Path

from . import caps_config
from .providers import _get_allowed_base_paths, _load_config, _parse_query


def get(handler, parts: list[str], query: dict):
    if len(parts) == 2 and parts[1] == "config":
        config = _load_config()
        fs = config.get("filesystem", {})
        raw_paths = fs.get("allowed_base_paths", [])
        expanded = [str(Path(p).expanduser().resolve()) for p in raw_paths if p]
        filesystem_settings = caps_config.load_filesystem_settings()
        return 200, {
            "filesystem": {
                "allowed_base_paths": expanded,
                "default_start_path": filesystem_settings["default_start_path"],
            },
            "default_caps": caps_config.load_caps(),
        }

    if len(parts) != 2 or parts[1] != "filesystem":
        return 404, {"error": "Not found"}

    requested = query.get("path", "")
    allowed = _get_allowed_base_paths()
    if not requested:
        requested = allowed[0] if allowed else str(Path.home())
    try:
        resolved = Path(requested).expanduser().resolve()
    except Exception:
        return 400, {"error": "invalid path"}
    if allowed and not any(str(resolved).startswith(ap) for ap in allowed):
        return 403, {"error": "path outside allowed directories"}
    if not resolved.exists() or not resolved.is_dir():
        return 404, {"error": "directory not found"}

    entries: list[dict] = []
    try:
        for entry in sorted(resolved.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            if entry.name.startswith("."):
                continue
            try:
                entries.append({"name": entry.name, "path": str(entry), "is_dir": entry.is_dir()})
            except PermissionError:
                continue
    except PermissionError:
        return 403, {"error": "permission denied"}

    parent: str | None = None
    if resolved.parent != resolved:
        parent_str = str(resolved.parent)
        if allowed:
            if any(parent_str == ap or parent_str.startswith(ap + "/") for ap in allowed):
                parent = parent_str
        else:
            parent = parent_str
    return 200, {"path": str(resolved), "entries": entries, "parent": parent}
