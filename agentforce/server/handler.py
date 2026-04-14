"""HTTP handler and routing for the AgentForce dashboard."""
from __future__ import annotations

import json as _jsonlib
import re
import signal as _signal
import threading
import time as _time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from . import state_io, ws
from . import watchers
from .routes import caps_config, daemon, filesystem, missions, models, plan, projects, providers, static, tasks

_daemon: Optional["MissionDaemon"] = None  # type: ignore[name-defined]  # noqa: F821

_STREAMS_DIR = Path.home() / ".agentforce" / "streams"
AGENTFORCE_HOME = state_io.AGENTFORCE_HOME
_UI_DIST = Path(__file__).parent.parent.parent / "ui" / "dist"
_SSE_TERMINAL = {"review_approved", "review_rejected", "failed", "blocked"}

_ROUTES: list[tuple[str, re.Pattern[str], object]] = [
    ("GET", re.compile(r"^/api/daemon(?:/.*)?$"), daemon.get),
    ("POST", re.compile(r"^/api/daemon(?:/.*)?$"), daemon.post),
    ("GET", re.compile(r"^/api/missions$"), missions.get),
    ("GET", re.compile(r"^/api/projects$"), projects.get),
    ("GET", re.compile(r"^/api/project/[^/]+$"), projects.get),
    ("POST", re.compile(r"^/api/projects$"), projects.post),
    ("POST", re.compile(r"^/api/project/[^/]+/(?:archive|unarchive)$"), projects.post),
    ("PATCH", re.compile(r"^/api/project/[^/]+$"), projects.patch),
    ("DELETE", re.compile(r"^/api/project/[^/]+$"), projects.delete),
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
    ("POST", re.compile(r"^/api/filesystem$"), filesystem.post),
    ("GET", re.compile(r"^/api/plan(?:/.*)?$"), plan.get),
    ("POST", re.compile(r"^/api/plan(?:/.*)?$"), plan.post),
    ("PATCH", re.compile(r"^/api/plan(?:/.*)?$"), plan.patch),
    ("DELETE", re.compile(r"^/api/plan(?:/.*)?$"), plan.delete),
    ("GET", re.compile(r"^/api/mission/[^/]+/task/[^/]+(?:/.*)?$"), tasks.get),
    ("POST", re.compile(r"^/api/mission/[^/]+/task/[^/]+(?:/.*)?$"), tasks.post),
    ("GET", re.compile(r"^/api/mission(?:/.*)?$"), missions.get),
    ("POST", re.compile(r"^/api/mission(?:/.*)?$"), missions.post),
    ("DELETE", re.compile(r"^/api/mission(?:/.*)?$"), missions.delete),
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

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
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


def serve(port: int = 8080, state_dir: Path | None = None, daemon: bool = False) -> None:
    global _daemon
    _daemon = None
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
        try:
            server = ThreadingHTTPServer((DashboardHandler.config.host, DashboardHandler.config.port), DashboardHandler)
        except PermissionError:
            if DashboardHandler.config.port != 0:
                raise
            # Some sandboxed test environments disallow ephemeral binds entirely.
            # Fall back to an unbound server object so startup wiring can still be tested.
            server = ThreadingHTTPServer(
                (DashboardHandler.config.host, DashboardHandler.config.port),
                DashboardHandler,
                bind_and_activate=False,
            )
            server.server_address = (DashboardHandler.config.host, DashboardHandler.config.port)
        watchdog = threading.Thread(
            target=watchers._watch_state_dir,
            kwargs={"state_dir": DashboardHandler.config.state_dir, "poll_seconds": 3.0},
            daemon=True,
            name="agentforce-state-watchdog",
        )
        watchdog.start()
        stream_watcher = threading.Thread(
            target=watchers._watch_stream_files,
            kwargs={"streams_dir": _STREAMS_DIR, "poll_seconds": 0.5},
            daemon=True,
            name="agentforce-stream-watcher",
        )
        stream_watcher.start()
        event_stream_watcher = threading.Thread(
            target=watchers._watch_stream_event_files,
            kwargs={"streams_dir": _STREAMS_DIR, "poll_seconds": 0.25},
            daemon=True,
            name="agentforce-event-stream-watcher",
        )
        event_stream_watcher.start()

        if daemon:
            import queue as _queue
            from agentforce.daemon import DaemonCallbacks, MissionDaemon
            from agentforce.server.routes.daemon import (
                _ws_on_complete,
                _ws_on_enqueue,
                _ws_on_fail,
                _ws_on_start,
                _ws_on_status_changed,
            )
            _daemon = MissionDaemon(
                state_dir=resolved_state_dir,
                notify_queue=_queue.Queue(),
                callbacks=DaemonCallbacks(
                    on_enqueue=_ws_on_enqueue,
                    on_start=_ws_on_start,
                    on_complete=_ws_on_complete,
                    on_fail=_ws_on_fail,
                    on_status_changed=_ws_on_status_changed,
                ),
            )
            shutdown_requested = threading.Event()

            def _handle_stop(signum=None, frame=None):
                if shutdown_requested.is_set():
                    return
                shutdown_requested.set()

                def _stop_server() -> None:
                    if _daemon is not None:
                        _daemon.stop()
                    server.shutdown()

                threading.Thread(
                    target=_stop_server,
                    daemon=True,
                    name="agentforce-server-shutdown",
                ).start()

            _signal.signal(_signal.SIGINT, _handle_stop)
            _signal.signal(_signal.SIGTERM, _handle_stop)
            _daemon.start()

        print(f"AgentForce Dashboard → http://{DashboardHandler.config.host}:{DashboardHandler.config.port}")
        print("Press Ctrl+C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            if _daemon is not None:
                _daemon.stop()
            print("\nDashboard stopped.")
    finally:
        state_io.set_state_dir(previous_override)
