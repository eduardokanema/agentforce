"""HTTP handler and routing for the AgentForce dashboard."""
from __future__ import annotations

import json as _jsonlib
import re
import threading
import time as _time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from . import state_io, ws
from .routes import caps_config, filesystem, missions, models, plan, providers, static, tasks

_STREAMS_DIR = Path.home() / ".agentforce" / "streams"
AGENTFORCE_HOME = state_io.AGENTFORCE_HOME
_UI_DIST = Path(__file__).parent.parent.parent / "ui" / "dist"
_SSE_TERMINAL = {"review_approved", "review_rejected", "failed", "blocked"}

_ROUTES: list[tuple[str, re.Pattern[str], object]] = [
    ("GET", re.compile(r"^/api/missions$"), missions.get),
    ("POST", re.compile(r"^/api/missions$"), missions.post),
    ("GET", re.compile(r"^/api/models(?:/default)?$"), models.get),
    ("POST", re.compile(r"^/api/models/default$"), models.post),
    ("GET", re.compile(r"^/api/providers(?:/.*)?$"), providers.get),
    ("POST", re.compile(r"^/api/providers(?:/.*)?$"), providers.post),
    ("DELETE", re.compile(r"^/api/providers(?:/.*)?$"), providers.delete),
    ("GET", re.compile(r"^/api/connectors(?:/.*)?$"), providers.get),
    ("POST", re.compile(r"^/api/connectors(?:/.*)?$"), providers.post),
    ("DELETE", re.compile(r"^/api/connectors(?:/.*)?$"), providers.delete),
    ("GET", re.compile(r"^/api/agents(?:/.*)?$"), providers.get),
    ("POST", re.compile(r"^/api/agents(?:/.*)?$"), providers.post),
    ("GET", re.compile(r"^/api/telemetry$"), providers.get),
    ("GET", re.compile(r"^/api/config$"), filesystem.get),
    ("POST", re.compile(r"^/api/config$"), caps_config.post),
    ("GET", re.compile(r"^/api/filesystem$"), filesystem.get),
    ("GET", re.compile(r"^/api/mission/[^/]+/task/[^/]+(?:/.*)?$"), tasks.get),
    ("POST", re.compile(r"^/api/mission/[^/]+/task/[^/]+(?:/.*)?$"), tasks.post),
    ("GET", re.compile(r"^/api/mission(?:/.*)?$"), missions.get),
    ("POST", re.compile(r"^/api/mission(?:/.*)?$"), missions.post),
    ("DELETE", re.compile(r"^/api/mission(?:/.*)?$"), missions.delete),
    ("POST", re.compile(r"^/api/plan$"), plan.post),
    ("GET", re.compile(r"^(?!/api).*$"), static.get),
]

def _parse_query(raw_path: str) -> dict[str, str]:
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(raw_path)
    qs = parse_qs(parsed.query)
    return {k: v[0] for k, v in qs.items() if v}


def _load_state(mission_id: str):
    return state_io._load_state(mission_id)

@dataclass(frozen=True)
class ServerConfig:
    state_dir: Path
    host: str
    port: int

class DashboardHandler(BaseHTTPRequestHandler):
    config = ServerConfig(state_dir=state_io.STATE_DIR, host="localhost", port=8080)

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def _handle_websocket(self):
        return static._handle_websocket(self)

    def _dispatch(self, method: str):
        clean_path = self.path.split("?")[0].rstrip("/") or "/"
        parts = [p for p in clean_path.split("/") if p]
        query = _parse_query(self.path)
        for route_method, pattern, fn in _ROUTES:
            if route_method != method or not pattern.match(clean_path):
                continue
            try:
                status, payload = fn(self, parts, query)
            except FileNotFoundError:
                self._json({"error": "Not found"}, status=404)
                return
            except ValueError as exc:
                self._json({"error": str(exc)}, status=400)
                return
            except Exception as exc:
                self._json({"error": str(exc)}, status=500)
                return
            if payload is None:
                return
            self._json(payload, status=status)
            return
        self._json({"error": "Not found"}, status=404)

    def _json(self, obj, status=200):
        encoded = _jsonlib.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length > 0 else b"{}"
        if not raw:
            return {}
        try:
            data = _jsonlib.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ValueError("invalid JSON body") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def _sse(self, mission_id: str, task_id: str) -> None:
        return static._sse(
            self,
            mission_id,
            task_id,
            load_state=_load_state,
            stream_dir=_STREAMS_DIR,
            terminal_statuses=_SSE_TERMINAL,
        )


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
    state_dir: Path | None = None,
    stop_event: threading.Event | None = None,
    poll_seconds: float = 3.0,
) -> None:
    state_root = Path(state_dir) if state_dir is not None else DashboardHandler.config.state_dir
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
    streams_dir: Path | None = None,
    stop_event: threading.Event | None = None,
    poll_seconds: float = 0.5,
) -> None:
    stream_root = streams_dir if streams_dir is not None else _STREAMS_DIR
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


def serve(port: int = 8080, state_dir: Path | None = None) -> None:
    previous_override = state_io._STATE_DIR_OVERRIDE
    try:
        resolved_state_dir = Path(state_dir) if state_dir is not None else state_io.STATE_DIR
        DashboardHandler.config = ServerConfig(
            state_dir=resolved_state_dir,
            host="localhost",
            port=port,
        )
        if state_dir is not None:
            state_io.set_state_dir(resolved_state_dir)
        server = ThreadingHTTPServer((DashboardHandler.config.host, DashboardHandler.config.port), DashboardHandler)
        watchdog = threading.Thread(
            target=_watch_state_dir,
            kwargs={"state_dir": DashboardHandler.config.state_dir, "poll_seconds": 3.0},
            daemon=True,
            name="agentforce-state-watchdog",
        )
        watchdog.start()
        stream_watcher = threading.Thread(
            target=_watch_stream_files,
            kwargs={"streams_dir": _STREAMS_DIR, "poll_seconds": 0.5},
            daemon=True,
            name="agentforce-stream-watcher",
        )
        stream_watcher.start()
        print(f"AgentForce Dashboard → http://{DashboardHandler.config.host}:{DashboardHandler.config.port}")
        print("Press Ctrl+C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nDashboard stopped.")
    finally:
        state_io.set_state_dir(previous_override)
