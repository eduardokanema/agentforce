"""Filesystem and config API route."""
from __future__ import annotations

from pathlib import Path

from . import caps_config
from .providers import _get_allowed_base_paths, _load_config, _parse_query


def _resolve_directory(path: str) -> tuple[Path | None, int | None, dict | None]:
    allowed = _get_allowed_base_paths()
    requested = path
    if not requested:
        requested = allowed[0] if allowed else str(Path.home())
    try:
        resolved = Path(requested).expanduser().resolve()
    except Exception:
        return None, 400, {"error": "invalid path"}
    if allowed and not any(str(resolved).startswith(ap) for ap in allowed):
        return None, 403, {"error": "path outside allowed directories"}
    if not resolved.exists() or not resolved.is_dir():
        return None, 404, {"error": "directory not found"}
    return resolved, None, None


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
    resolved, error_status, error_payload = _resolve_directory(requested)
    if error_payload is not None:
        return error_status, error_payload
    assert resolved is not None

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
        allowed = _get_allowed_base_paths()
        if allowed:
            if any(parent_str == ap or parent_str.startswith(ap + "/") for ap in allowed):
                parent = parent_str
        else:
            parent = parent_str
    return 200, {"path": str(resolved), "entries": entries, "parent": parent}


def post(handler, parts: list[str], query: dict):
    if len(parts) != 2 or parts[1] != "filesystem":
        return 404, {"error": "Not found"}

    body = handler._read_json_body()
    base_path = body.get("path")
    folder_name = body.get("name")
    if not isinstance(base_path, str) or not base_path.strip():
        return 400, {"error": "path is required"}
    if not isinstance(folder_name, str) or not folder_name.strip():
        return 400, {"error": "name is required"}

    resolved, error_status, error_payload = _resolve_directory(base_path)
    if error_payload is not None:
        return error_status, error_payload
    assert resolved is not None

    folder_segment = folder_name.strip()
    if folder_segment in {".", ".."} or "/" in folder_segment or "\\" in folder_segment:
        return 400, {"error": "invalid folder name"}

    created_path = resolved / folder_segment
    if created_path.exists():
        return 409, {"error": "directory already exists"}
    try:
        created_path.mkdir(parents=False, exist_ok=False)
    except PermissionError:
        return 403, {"error": "permission denied"}

    return 201, {"path": str(created_path.resolve())}
