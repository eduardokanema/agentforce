"""Background file watchers for the AgentForce dashboard."""
from __future__ import annotations

import json as _jsonlib
import threading
import time as _time
from pathlib import Path

from . import state_io, ws

def _state_file_signature(state_dir: Path) -> dict[str, int]:
    if not state_dir.exists():
        return {}
    signature = {}
    for sf in state_dir.glob("*.json"):
        try:
            signature[sf.name] = sf.stat().st_mtime_ns
        except OSError:
            continue
    return signature

def _watch_state_dir(
    state_dir: Path,
    stop_event: threading.Event | None = None,
    poll_seconds: float = 3.0,
) -> None:
    state_root = Path(state_dir)
    last_signature = _state_file_signature(state_root)
    while stop_event is None or not stop_event.is_set():
        _time.sleep(poll_seconds)
        current_signature = _state_file_signature(state_root)
        if current_signature == last_signature:
            continue
        last_signature = current_signature
        try:
            ws.broadcast_mission_list([mission.to_summary_dict() for mission in state_io._load_all_missions(state_root)])
        except Exception:
            pass

def _watch_stream_files(
    streams_dir: Path,
    stop_event: threading.Event | None = None,
    poll_seconds: float = 0.5,
) -> None:
    stream_root = Path(streams_dir)
    # stem -> (byte_position, seq)
    positions: dict[str, tuple[int, int]] = {}
    while stop_event is None or not stop_event.is_set():
        _time.sleep(poll_seconds)
        if not stream_root.exists():
            continue
        try:
            log_files = list(stream_root.glob("*.log"))
        except OSError:
            continue
        for log_file in log_files:
            stem = log_file.stem  # e.g. "76dab286_01"
            idx = stem.find("_")
            if idx < 0:
                continue
            mission_id, task_id = stem[:idx], stem[idx + 1:]
            pos, seq = positions.get(stem, (0, 0))
            try:
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    chunk = f.read()
                    new_pos = f.tell()
            except OSError:
                continue
            if chunk:
                for line in chunk.splitlines():
                    seq += 1
                    ws.broadcast_stream_line(mission_id, task_id, line, seq)
                positions[stem] = (new_pos, seq)

def _watch_stream_event_files(
    streams_dir: Path,
    stop_event: threading.Event | None = None,
    poll_seconds: float = 0.25,
) -> None:
    stream_root = Path(streams_dir)
    positions: dict[str, int] = {}
    while stop_event is None or not stop_event.is_set():
        _time.sleep(poll_seconds)
        if not stream_root.exists():
            continue
        try:
            event_files = list(stream_root.glob("*.events.jsonl"))
        except OSError:
            continue
        for event_file in event_files:
            stem = event_file.name.removesuffix(".events.jsonl")
            idx = stem.find("_")
            if idx < 0:
                continue
            mission_id, task_id = stem[:idx], stem[idx + 1 :]
            pos = positions.get(stem, 0)
            try:
                with open(event_file, "r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(pos)
                    chunk = fh.read()
                    new_pos = fh.tell()
            except OSError:
                continue
            if not chunk:
                continue
            for line in chunk.splitlines():
                if not line.strip():
                    continue
                try:
                    payload = _jsonlib.loads(line)
                except _jsonlib.JSONDecodeError:
                    continue
                ws.broadcast_task_stream_event(mission_id, task_id, payload)
            positions[stem] = new_pos
