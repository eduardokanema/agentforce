"""HTTP handler and routing for the AgentForce dashboard."""
from __future__ import annotations

import json as _json
import os
import time as _time
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path

from .render import render_mission_list, render_mission_detail, render_task_detail

_STREAMS_DIR = Path.home() / ".agentforce" / "streams"
_SSE_TERMINAL = {"review_approved", "review_rejected", "failed", "blocked"}

AGENTFORCE_HOME = Path(os.path.expanduser("~/.agentforce"))
STATE_DIR = AGENTFORCE_HOME / "state"
_STATIC_DIR = Path(__file__).parent / "static"


def _load_all_missions() -> list:
    if not STATE_DIR.exists():
        return []
    from agentforce.core.state import MissionState
    missions = []
    for sf in sorted(STATE_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            missions.append(MissionState.load(sf))
        except Exception:
            pass
    return missions


def _load_state(mission_id: str):
    from agentforce.core.state import MissionState
    if not STATE_DIR.exists():
        return None
    for sf in STATE_DIR.glob("*.json"):
        if sf.stem == mission_id or sf.stem.startswith(mission_id):
            try:
                return MissionState.load(sf)
            except Exception:
                return None
    return None


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        parts = [p for p in path.split("/") if p]

        # Serve static files
        if parts and parts[0] == "static":
            self._serve_static("/".join(parts[1:]))
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
                    msg += f"data: {_json.dumps({'line': line})}\n\n".encode()
                elif event:
                    msg += b"data: {}\n\n"
                self.wfile.write(msg)
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, OSError):
                return False

        pos = 0
        idle = 0
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
                                    _send(ln)
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
    print(f"AgentForce Dashboard → http://localhost:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
