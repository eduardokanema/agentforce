"""Static HTML, SPA, and legacy SSE routes."""
from __future__ import annotations

import json as _jsonlib
import time as _time
from pathlib import Path

from .. import state_io, ws
from ..render import render_mission_detail, render_mission_list, render_task_detail


def _handler():
    from .. import handler as _handler_mod

    return _handler_mod


def _send_html(handler, content: str) -> None:
    encoded = content.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def _send_error(handler, code: int, msg: str) -> None:
    from ..render import _page

    body = _page("Error", f'<p class="empty">{msg}</p>').encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _serve_static(handler, filename: str) -> None:
    static_dir = Path(__file__).parent.parent / "static"
    filepath = static_dir / filename
    if not filepath.exists() or not filepath.is_file():
        _send_error(handler, 404, "Static file not found")
        return
    ext = filepath.suffix.lower()
    mime = {".css": "text/css", ".js": "application/javascript", ".png": "image/png", ".svg": "image/svg+xml"}.get(ext, "application/octet-stream")
    data = filepath.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    handler.wfile.write(data)


def _serve_spa(handler, parts: list[str]) -> None:
    ui_dist = _handler()._UI_DIST
    mime = {
        ".js": "application/javascript",
        ".css": "text/css",
        ".html": "text/html; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".ico": "image/x-icon",
        ".woff2": "font/woff2",
        ".woff": "font/woff",
    }
    if parts:
        candidate = ui_dist / "/".join(parts)
        if candidate.exists() and candidate.is_file():
            data = candidate.read_bytes()
            handler.send_response(200)
            handler.send_header("Content-Type", mime.get(candidate.suffix.lower(), "application/octet-stream"))
            handler.send_header("Content-Length", str(len(data)))
            handler.send_header("Cache-Control", "public, max-age=31536000, immutable" if "/assets/" in handler.path else "no-cache")
            handler.end_headers()
            handler.wfile.write(data)
            return
    index = ui_dist / "index.html"
    data = index.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    handler.wfile.write(data)


def _handle_websocket(handler) -> None:
    if not ws.handshake(handler):
        return
    conn = ws.WsConnection(handler.connection)
    current_bucket = "*"
    ws.register(conn, current_bucket)
    try:
        while True:
            msg = conn.recv_text()
            if msg is None:
                break
            try:
                payload = __import__("json").loads(msg)
            except Exception:
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
                conn.send_text(__import__("json").dumps({"type": "pong"}))
    except OSError:
        pass
    finally:
        ws.unregister(conn)
        conn.close()


def get(handler, parts: list[str], query: dict) -> tuple[int, dict | None]:
    if handler.headers.get("Upgrade", "").lower() == "websocket":
        _handle_websocket(handler)
        return 200, None

    if parts and parts[0] == "static":
        _serve_static(handler, "/".join(parts[1:]))
        return 200, None

    if _handler()._UI_DIST.exists():
        _serve_spa(handler, parts)
        return 200, None

    try:
        if not parts:
            _send_html(handler, render_mission_list(state_io._load_all_missions()))
            return 200, None
        if len(parts) == 2 and parts[0] == "mission":
            state = state_io._load_state(parts[1])
            if state:
                _send_html(handler, render_mission_detail(state))
            else:
                _send_error(handler, 404, f"Mission {parts[1]!r} not found")
            return 200, None
        if len(parts) == 5 and parts[0] == "mission" and parts[2] == "task" and parts[4] == "stream":
            _sse(handler, parts[1], parts[3])
            return 200, None
        if len(parts) == 4 and parts[0] == "mission" and parts[2] == "task":
            state = state_io._load_state(parts[1])
            if state:
                _send_html(handler, render_task_detail(state, parts[3]))
            else:
                _send_error(handler, 404, f"Mission {parts[1]!r} not found")
            return 200, None
        _send_error(handler, 404, "Not found")
        return 404, None
    except Exception as exc:
        _send_error(handler, 500, str(exc))
        return 500, None


def _sse(
    handler,
    mission_id: str,
    task_id: str,
    load_state=state_io._load_state,
    stream_dir: Path | None = None,
    terminal_statuses: set[str] | None = None,
):
    stream_root = Path(stream_dir) if stream_dir is not None else state_io.get_agentforce_home() / "streams"
    stream_file = stream_root / f"{mission_id}_{task_id}.log"
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "keep-alive")
    handler.end_headers()

    def _send(line=None, event=None) -> bool:
        try:
            msg = b""
            if event:
                msg += f"event: {event}\n".encode()
            if line is not None:
                msg += f"data: {_jsonlib.dumps({'line': line})}\n\n".encode()
            elif event:
                msg += b"data: {}\n\n"
            handler.wfile.write(msg)
            handler.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    pos = 0
    idle = 0
    seq = 0
    try:
        while idle < 180:
            try:
                handler.wfile.write(b": ping\n\n")
                handler.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

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

            state = load_state(mission_id)
            if state:
                ts = state.task_states.get(task_id)
                if ts and ts.status in (terminal_statuses or _handler()._SSE_TERMINAL):
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
