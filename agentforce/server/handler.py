"""HTTP handler and routing for the AgentForce dashboard."""
from __future__ import annotations

import json as _jsonlib
import os
import threading
import time as _time
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path

from .render import render_mission_list, render_mission_detail, render_task_detail
from . import ws

_STREAMS_DIR = Path.home() / ".agentforce" / "streams"
_SSE_TERMINAL = {"review_approved", "review_rejected", "failed", "blocked"}

AGENTFORCE_HOME = Path(os.path.expanduser("~/.agentforce"))
STATE_DIR = AGENTFORCE_HOME / "state"
_STATIC_DIR = Path(__file__).parent / "static"
_UI_DIST = Path(__file__).parent.parent.parent / "ui" / "dist"


def _load_all_missions(state_dir: Path | None = None) -> list:
    state_root = Path(state_dir) if state_dir is not None else STATE_DIR
    if not state_root.exists():
        return []
    from agentforce.core.state import MissionState
    missions = []
    for sf in sorted(state_root.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            missions.append(MissionState.load(sf))
        except Exception:
            pass
    return missions


def _load_state(mission_id: str, state_dir: Path | None = None):
    from agentforce.core.state import MissionState
    state_root = Path(state_dir) if state_dir is not None else STATE_DIR
    if not state_root.exists():
        return None
    for sf in state_root.glob("*.json"):
        if sf.stem == mission_id or sf.stem.startswith(mission_id):
            try:
                return MissionState.load(sf)
            except Exception:
                return None
    return None


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
    state_root = Path(state_dir) if state_dir is not None else STATE_DIR
    last_signature = _state_file_signature(state_root)

    while stop_event is None or not stop_event.is_set():
        _time.sleep(poll_seconds)
        current_signature = _state_file_signature(state_root)
        if current_signature == last_signature:
            continue
        last_signature = current_signature
        try:
            ws.broadcast_mission_list(
                [mission.to_summary_dict() for mission in _load_all_missions(state_root)]
            )
        except Exception:
            pass


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.headers.get("Upgrade", "").lower() == "websocket":
            self._handle_websocket()
            return

        path = self.path.split("?")[0].rstrip("/") or "/"
        parts = [p for p in path.split("/") if p]

        if parts and parts[0] == "api":
            self._handle_api(parts)
            return

        # Serve static files (legacy)
        if parts and parts[0] == "static":
            self._serve_static("/".join(parts[1:]))
            return

        # Serve React SPA (ui/dist/) if built, otherwise fall back to server-rendered HTML
        if _UI_DIST.exists():
            self._serve_spa(parts)
            return

        try:
            if not parts:
                self._html(render_mission_list(_load_all_missions()))
            elif len(parts) == 2 and parts[0] == "mission":
                state = _load_state(parts[1])
                if state:
                    self._html(render_mission_detail(state))
                else:
                    self._err(404, f"Mission {parts[1]!r} not found")
            elif (len(parts) == 5 and parts[0] == "mission"
                  and parts[2] == "task" and parts[4] == "stream"):
                self._sse(parts[1], parts[3])
            elif len(parts) == 4 and parts[0] == "mission" and parts[2] == "task":
                state = _load_state(parts[1])
                if state:
                    self._html(render_task_detail(state, parts[3]))
                else:
                    self._err(404, f"Mission {parts[1]!r} not found")
            else:
                self._err(404, "Not found")
        except Exception as exc:
            self._err(500, str(exc))

    def _handle_websocket(self):
        if not ws.handshake(self):
            return

        conn = ws.WsConnection(self.connection)
        current_bucket = "*"
        ws.register(conn, current_bucket)

        try:
            while True:
                msg = conn.recv_text()
                if msg is None:
                    break

                try:
                    payload = _jsonlib.loads(msg)
                except _jsonlib.JSONDecodeError:
                    continue

                msg_type = payload.get("type")
                if msg_type == "subscribe_all":
                    ws.unregister(conn, current_bucket)
                    current_bucket = "*"
                    ws.register(conn, current_bucket)
                elif msg_type == "subscribe":
                    mission_id = payload.get("mission_id")
                    if not mission_id:
                        continue
                    ws.unregister(conn, current_bucket)
                    current_bucket = mission_id
                    ws.register(conn, current_bucket)
                elif msg_type == "ping":
                    conn.send_text(_jsonlib.dumps({"type": "pong"}))
        except OSError:
            pass
        finally:
            ws.unregister(conn)
            conn.close()

    def _handle_api(self, parts: list[str]):
        if len(parts) == 2 and parts[1] == "missions":
            missions = _load_all_missions()
            self._json([mission.to_summary_dict() for mission in missions])
            return

        if len(parts) == 3 and parts[1] == "mission":
            state = _load_state(parts[2])
            if not state:
                self._json({"error": f"Mission {parts[2]!r} not found"}, status=404)
                return
            self._json(state.to_dict())
            return

        if len(parts) == 5 and parts[1] == "mission" and parts[3] == "task":
            state = _load_state(parts[2])
            if not state:
                self._json({"error": f"Mission {parts[2]!r} not found"}, status=404)
                return
            task_state = state.task_states.get(parts[4])
            if not task_state:
                self._json(
                    {"error": f"Task {parts[4]!r} not found in mission {parts[2]!r}"},
                    status=404,
                )
                return
            task_spec = next((task for task in state.spec.tasks if task.id == parts[4]), None)
            payload = task_state.to_dict()
            if task_spec:
                payload.update(task_spec.to_dict())
            self._json(payload)
            return

        self._json({"error": "Not found"}, status=404)

    def _serve_spa(self, parts: list[str]):
        """Serve the React SPA from ui/dist/. Static assets are served directly;
        all other paths return index.html so React Router handles routing."""
        _MIME = {
            ".js": "application/javascript",
            ".css": "text/css",
            ".html": "text/html; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
            ".woff2": "font/woff2",
            ".woff": "font/woff",
        }
        # Try to serve a real file from dist (assets, favicon, etc.)
        if parts:
            candidate = _UI_DIST / "/".join(parts)
            if candidate.exists() and candidate.is_file():
                data = candidate.read_bytes()
                mime = _MIME.get(candidate.suffix.lower(), "application/octet-stream")
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "public, max-age=31536000, immutable"
                                 if "/assets/" in self.path else "no-cache")
                self.end_headers()
                self.wfile.write(data)
                return
        # SPA fallback: all other routes → index.html
        index = _UI_DIST / "index.html"
        data = index.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self, filename: str):
        filepath = _STATIC_DIR / filename
        if not filepath.exists() or not filepath.is_file():
            self._err(404, "Static file not found")
            return
        ext = filepath.suffix.lower()
        mime = {".css": "text/css", ".js": "application/javascript",
                ".png": "image/png", ".svg": "image/svg+xml"}.get(ext, "application/octet-stream")
        data = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _html(self, content: str):
        encoded = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _json(self, obj, status=200):
        encoded = _jsonlib.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _sse(self, mission_id: str, task_id: str):
        """Stream live agent output as Server-Sent Events."""
        stream_file = _STREAMS_DIR / f"{mission_id}_{task_id}.log"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def _send(line=None, event=None) -> bool:
            try:
                msg = b""
                if event:
                    msg += f"event: {event}\n".encode()
                if line is not None:
                    msg += f"data: {_jsonlib.dumps({'line': line})}\n\n".encode()
                elif event:
                    msg += b"data: {}\n\n"
                self.wfile.write(msg)
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, OSError):
                return False

        pos = 0
        idle = 0
        seq = 0
        try:
            while idle < 180:
                # Keepalive comment
                try:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return

                # Drain new content from stream file
                if stream_file.exists():
                    with open(stream_file, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(pos)
                        chunk = f.read()
                        pos = f.tell()
                    if chunk:
                        idle = 0
                        for ln in chunk.splitlines():
                            seq += 1
                            ws.broadcast_stream_line(mission_id, task_id, ln, seq)
                            if not _send(ln):
                                return
                    else:
                        idle += 1
                else:
                    idle += 1

                # Check if task reached a terminal status
                state = _load_state(mission_id)
                if state:
                    ts = state.task_states.get(task_id)
                    if ts and ts.status in _SSE_TERMINAL:
                        # Drain any remaining content
                        if stream_file.exists():
                            with open(stream_file, "r", encoding="utf-8", errors="replace") as f:
                                f.seek(pos)
                                for ln in f.read().splitlines():
                                    seq += 1
                                    ws.broadcast_stream_line(mission_id, task_id, ln, seq)
                                    _send(ln)
                        ws.broadcast_task_stream_done(mission_id, task_id)
                        _send(event="done")
                        return

                _time.sleep(1)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _err(self, code: int, msg: str):
        from .render import _page
        body = _page("Error", f'<p class="empty">{msg}</p>').encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(port: int = 8080, state_dir: Path | None = None) -> None:
    global STATE_DIR
    if state_dir is not None:
        STATE_DIR = Path(state_dir)
    server = ThreadingHTTPServer(("localhost", port), DashboardHandler)
    watchdog = threading.Thread(
        target=_watch_state_dir,
        kwargs={"state_dir": STATE_DIR, "poll_seconds": 3.0},
        daemon=True,
        name="agentforce-state-watchdog",
    )
    watchdog.start()
    print(f"AgentForce Dashboard → http://localhost:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
