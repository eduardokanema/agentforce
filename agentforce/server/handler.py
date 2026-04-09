"""HTTP handler and routing for the AgentForce dashboard."""
from __future__ import annotations

import json as _jsonlib
import os
import threading
import time as _time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import request as urllib_request

import yaml

from .render import render_mission_list, render_mission_detail, render_task_detail
from . import ws

_STREAMS_DIR = Path.home() / ".agentforce" / "streams"
_SSE_TERMINAL = {"review_approved", "review_rejected", "failed", "blocked"}

AGENTFORCE_HOME = Path(os.path.expanduser("~/.agentforce"))
STATE_DIR = AGENTFORCE_HOME / "state"
_STATIC_DIR = Path(__file__).parent / "static"
_UI_DIST = Path(__file__).parent.parent.parent / "ui" / "dist"
_KNOWN_CONNECTORS = {
    "github": "GitHub",
    "slack": "Slack",
    "linear": "Linear",
    "sentry": "Sentry",
    "notion": "Notion",
    "anthropic": "Anthropic",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _format_duration(started_at: str | None, completed_at: str | None = None) -> str:
    started = _parse_iso_datetime(started_at)
    if started is None:
        return "?"
    ended = _parse_iso_datetime(completed_at) if completed_at else datetime.now(timezone.utc)
    if ended is None:
        return "?"
    seconds = max(0, int((ended - started).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


def _connectors_path() -> Path:
    return AGENTFORCE_HOME / "connectors.json"


def _load_connectors_metadata() -> dict[str, dict[str, Any]]:
    path = _connectors_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("{}", encoding="utf-8")
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = _jsonlib.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_connectors_metadata(data: dict[str, dict[str, Any]]) -> None:
    path = _connectors_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        _jsonlib.dump(data, fh, indent=2)


def _task_status_value(task_state) -> str:
    status = getattr(task_state.status, "value", task_state.status)
    return str(status)


def _make_mission_state_from_spec(spec):
    from agentforce.core.state import MissionState, TaskState

    mission_id = spec.short_id()
    state = MissionState(mission_id=mission_id, spec=spec)
    state.working_dir = str(Path(spec.working_dir or f"./missions-{mission_id}").resolve())
    for task_spec in spec.tasks:
        state.task_states[task_spec.id] = TaskState(
            task_id=task_spec.id,
            spec_summary=f"{task_spec.title}"[:200],
        )
    return state


def _state_path(mission_id: str) -> Path:
    return STATE_DIR / f"{mission_id}.json"


def _inject_path(mission_id: str, task_id: str) -> Path:
    return AGENTFORCE_HOME / "state" / mission_id / f"{task_id}.inject"


def _broadcast_mission_refresh(state) -> None:
    try:
        ws.broadcast_mission(state.mission_id, state.to_dict())
        ws.broadcast_mission_list([mission.to_summary_dict() for mission in _load_all_missions()])
    except Exception:
        pass


def _broadcast_mission_list_refresh() -> None:
    try:
        ws.broadcast_mission_list([mission.to_summary_dict() for mission in _load_all_missions()])
    except Exception:
        pass


def _connector_test_request(name: str, token: str) -> None:
    if not token:
        raise ValueError("no token configured")

    if name == "github":
        req = urllib_request.Request(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "AgentForce",
            },
        )
        urllib_request.urlopen(req, timeout=10)
        return

    if name == "slack":
        req = urllib_request.Request(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib_request.urlopen(req, timeout=10) as resp:
            payload = _jsonlib.loads(resp.read().decode("utf-8") or "{}")
        if not payload.get("ok"):
            raise RuntimeError(payload.get("error", "slack auth failed"))
        return

    if name == "linear":
        req = urllib_request.Request(
            "https://api.linear.app/graphql",
            data=_jsonlib.dumps({"query": "{ viewer { id } }"}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        urllib_request.urlopen(req, timeout=10)
        return

    if name == "sentry":
        req = urllib_request.Request(
            "https://sentry.io/api/0/",
            headers={"Authorization": f"Bearer {token}"},
        )
        urllib_request.urlopen(req, timeout=10)
        return

    if name == "notion":
        req = urllib_request.Request(
            "https://api.notion.com/v1/users/me",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": "2022-06-28",
            },
        )
        urllib_request.urlopen(req, timeout=10)
        return

    if name == "anthropic":
        from anthropic import Anthropic

        client = Anthropic(api_key=token)
        client.models.list()
        return

    if not token.strip():
        raise ValueError("no token configured")


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

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        parts = [p for p in path.split("/") if p]
        if not parts or parts[0] != "api":
            self._json({"error": "Not found"}, status=404)
            return

        try:
            body = self._read_json_body()
        except ValueError as exc:
            self._json({"error": str(exc)}, status=400)
            return

        try:
            if len(parts) == 2 and parts[1] == "missions":
                self._post_missions(body)
                return
            if len(parts) == 2 and parts[1] == "plan":
                self._post_plan(body)
                return
            if len(parts) == 4 and parts[1] == "mission" and parts[3] == "stop":
                self._post_mission_stop(parts[2])
                return
            if len(parts) == 4 and parts[1] == "mission" and parts[3] == "restart":
                self._post_mission_restart(parts[2])
                return
            if len(parts) == 6 and parts[1] == "mission" and parts[3] == "task":
                if parts[5] == "stop":
                    self._post_task_stop(parts[2], parts[4])
                    return
                if parts[5] == "retry":
                    self._post_task_retry(parts[2], parts[4])
                    return
                if parts[5] == "inject":
                    self._post_task_inject(parts[2], parts[4], body)
                    return
                if parts[5] == "resolve":
                    self._post_task_resolve(parts[2], parts[4], body)
                    return
            if len(parts) == 4 and parts[1] == "connectors":
                if parts[3] == "configure":
                    self._post_connector_configure(parts[2], body)
                    return
                if parts[3] == "test":
                    self._post_connector_test(parts[2])
                    return
        except FileNotFoundError:
            self._json({"error": "Not found"}, status=404)
            return
        except Exception as exc:
            self._json({"error": str(exc)}, status=500)
            return

        self._json({"error": "Not found"}, status=404)

    def do_DELETE(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        parts = [p for p in path.split("/") if p]
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "connectors":
            self._delete_connector(parts[2])
            return
        self._json({"error": "Not found"}, status=404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

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

        if len(parts) == 2 and parts[1] == "models":
            self._json([
                {
                    "id": "claude-opus-4-5",
                    "name": "Claude Opus 4.5",
                    "provider": "Anthropic",
                    "cost_per_1k_input": 0.015,
                    "cost_per_1k_output": 0.075,
                    "latency_label": "Powerful",
                },
                {
                    "id": "claude-sonnet-4-5",
                    "name": "Claude Sonnet 4.5",
                    "provider": "Anthropic",
                    "cost_per_1k_input": 0.003,
                    "cost_per_1k_output": 0.015,
                    "latency_label": "Standard",
                },
                {
                    "id": "claude-haiku-4-5",
                    "name": "Claude Haiku 4.5",
                    "provider": "Anthropic",
                    "cost_per_1k_input": 0.00025,
                    "cost_per_1k_output": 0.00125,
                    "latency_label": "Fast",
                },
            ])
            return

        if len(parts) == 2 and parts[1] == "connectors":
            metadata = _load_connectors_metadata()
            try:
                import keyring
            except Exception as exc:
                self._json({"error": str(exc)}, status=500)
                return
            connectors = []
            for name, display_name in _KNOWN_CONNECTORS.items():
                token = None
                try:
                    token = keyring.get_password("agentforce", name)
                except Exception:
                    token = None
                connectors.append({
                    "name": name,
                    "display_name": display_name,
                    "active": token is not None,
                    "last_configured": metadata.get(name, {}).get("last_configured"),
                })
            self._json(connectors)
            return

        if len(parts) == 2 and parts[1] == "telemetry":
            missions = _load_all_missions()
            total_tasks = 0
            total_cost = 0.0
            total_tokens_in = 0
            total_tokens_out = 0
            missions_by_cost = []
            tasks_by_cost = []
            retry_distribution = {"0": 0, "1": 0, "2+": 0}
            cost_over_time = []

            for state in missions:
                total_tasks += len(state.task_states)
                total_cost += state.cost_usd
                total_tokens_in += state.tokens_in
                total_tokens_out += state.tokens_out
                missions_by_cost.append({
                    "mission_id": state.mission_id,
                    "name": state.spec.name,
                    "cost_usd": state.cost_usd,
                    "tokens_in": state.tokens_in,
                    "tokens_out": state.tokens_out,
                    "duration": _format_duration(state.started_at, state.completed_at),
                    "retries": state.total_retries,
                })
                for task_id, task_state in state.task_states.items():
                    task_spec = next((task for task in state.spec.tasks if task.id == task_id), None)
                    tasks_by_cost.append({
                        "mission_id": state.mission_id,
                        "task_id": task_id,
                        "task": task_spec.title if task_spec else task_id,
                        "mission": state.spec.name,
                        "model": state.worker_model,
                        "cost_usd": task_state.cost_usd,
                        "retries": task_state.retries,
                    })
                    if task_state.retries <= 0:
                        retry_distribution["0"] += 1
                    elif task_state.retries == 1:
                        retry_distribution["1"] += 1
                    else:
                        retry_distribution["2+"] += 1

            ordered_missions = sorted(
                missions,
                key=lambda state: (
                    _parse_iso_datetime(state.started_at) or datetime.min.replace(tzinfo=timezone.utc),
                    state.mission_id,
                ),
            )
            cumulative_cost = 0.0
            for state in ordered_missions:
                cumulative_cost += state.cost_usd
                cost_over_time.append({
                    "mission_name": state.spec.name,
                    "cumulative_cost": round(cumulative_cost, 4),
                })

            missions_by_cost.sort(key=lambda item: item["cost_usd"], reverse=True)
            tasks_by_cost.sort(key=lambda item: item["cost_usd"], reverse=True)
            self._json({
                "total_missions": len(missions),
                "total_tasks": total_tasks,
                "total_cost_usd": total_cost,
                "total_tokens_in": total_tokens_in,
                "total_tokens_out": total_tokens_out,
                "missions_by_cost": missions_by_cost[:5],
                "tasks_by_cost": tasks_by_cost[:5],
                "retry_distribution": retry_distribution,
                "cost_over_time": cost_over_time,
            })
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

        if len(parts) == 6 and parts[1] == "mission" and parts[3] == "task" and parts[5] == "attempts":
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
            history = getattr(task_state, "attempt_history", None)
            if not history:
                history = getattr(task_state, "attempts", None)
            if not history:
                self._json([{
                    "attempt_number": 1,
                    "output": task_state.worker_output,
                    "review": task_state.review_feedback or None,
                    "score": task_state.review_score,
                }])
                return
            records = []
            for idx, attempt in enumerate(history, start=1):
                if isinstance(attempt, dict):
                    records.append({
                        "attempt_number": attempt.get("attempt_number", attempt.get("attempt", idx)),
                        "output": attempt.get("output", ""),
                        "review": attempt.get("review"),
                        "score": attempt.get("score"),
                    })
                else:
                    records.append({
                        "attempt_number": idx,
                        "output": str(attempt),
                        "review": None,
                        "score": None,
                    })
            self._json(records)
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
        self.send_header("Access-Control-Allow-Origin", "*")
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

    def _post_missions(self, body: dict) -> None:
        yaml_text = body.get("yaml")
        if not isinstance(yaml_text, str) or not yaml_text.strip():
            self._json({"error": "yaml is required"}, status=400)
            return
        try:
            from agentforce.core.spec import MissionSpec

            spec = MissionSpec.from_dict(yaml.safe_load(yaml_text))
        except Exception as exc:
            self._json({"error": f"invalid mission yaml: {str(exc)}"}, status=400)
            return

        state = _make_mission_state_from_spec(spec)
        state.log_event("mission_started", details="Started via API")
        _state_path(state.mission_id).parent.mkdir(parents=True, exist_ok=True)
        state.save(_state_path(state.mission_id))
        _broadcast_mission_refresh(state)

        def _runner():
            try:
                from agentforce.autonomous import run_autonomous

                run_autonomous(state.mission_id)
            except SystemExit:
                pass
            except Exception:
                pass

        threading.Thread(target=_runner, daemon=True, name=f"agentforce-mission-{state.mission_id}").start()
        self._json({"id": state.mission_id, "status": "started"})

    def _post_plan(self, body: dict) -> None:
        prompt = body.get("prompt")
        approved_models = body.get("approved_models") or []
        workspace = body.get("workspace", "")
        if not isinstance(prompt, str) or not prompt.strip():
            self._json({"error": "prompt is required"}, status=400)
            return

        try:
            import keyring
            from anthropic import Anthropic
        except Exception as exc:
            self._json({"error": str(exc)}, status=500)
            return

        api_key = None
        try:
            api_key = keyring.get_password("agentforce", "anthropic")
        except Exception:
            api_key = None
        if not api_key:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            self._json({"error": "anthropic connector is not configured"}, status=400)
            return

        model = approved_models[0] if isinstance(approved_models, list) and approved_models else "claude-sonnet-4-5"
        system_prompt = (
            "You are AgentForce's mission planner. Output valid YAML only in the "
            "AgentForce mission format. Do not wrap the YAML in markdown fences, "
            "comments, or prose."
        )
        user_prompt = (
            f"Workspace: {workspace}\n\n"
            f"Approved models: {approved_models}\n\n"
            f"User prompt:\n{prompt}\n"
        )

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        client = Anthropic(api_key=api_key)
        try:
            with client.messages.stream(
                model=model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            ) as stream:
                for chunk in stream.text_stream:
                    if not chunk:
                        continue
                    self.wfile.write(f"data: {chunk}\n\n".encode("utf-8"))
                    self.wfile.flush()
        except Exception as exc:
            self.wfile.write(f"data: {str(exc)}\n\n".encode("utf-8"))
            self.wfile.flush()
        finally:
            try:
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except OSError:
                pass

    def _post_mission_stop(self, mission_id: str) -> None:
        state = _load_state(mission_id)
        if not state:
            self._json({"error": f"Mission {mission_id!r} not found"}, status=404)
            return
        changed = False
        for task_state in state.task_states.values():
            if _task_status_value(task_state) == "in_progress":
                task_state.status = "blocked"
                changed = True
        if changed:
            state.save(_state_path(mission_id))
            _broadcast_mission_refresh(state)
        self._json({"stopped": True})

    def _post_mission_restart(self, mission_id: str) -> None:
        state = _load_state(mission_id)
        if not state:
            self._json({"error": f"Mission {mission_id!r} not found"}, status=404)
            return
        requeued = 0
        for task_state in state.task_states.values():
            if _task_status_value(task_state) in {"failed", "blocked", "review_rejected"}:
                task_state.status = "pending"
                task_state.worker_output = ""
                requeued += 1
        state.save(_state_path(mission_id))
        _broadcast_mission_list_refresh()
        self._json({"requeued": requeued})

    def _post_task_stop(self, mission_id: str, task_id: str) -> None:
        state = _load_state(mission_id)
        if not state:
            self._json({"error": f"Mission {mission_id!r} not found"}, status=404)
            return
        task_state = state.task_states.get(task_id)
        if not task_state:
            self._json({"error": f"Task {task_id!r} not found in mission {mission_id!r}"}, status=404)
            return
        task_state.status = "blocked"
        state.save(_state_path(mission_id))
        _broadcast_mission_refresh(state)
        self._json({"stopped": True})

    def _post_task_retry(self, mission_id: str, task_id: str) -> None:
        state = _load_state(mission_id)
        if not state:
            self._json({"error": f"Mission {mission_id!r} not found"}, status=404)
            return
        task_state = state.task_states.get(task_id)
        if not task_state:
            self._json({"error": f"Task {task_id!r} not found in mission {mission_id!r}"}, status=404)
            return
        task_state.status = "pending"
        task_state.worker_output = ""
        task_state.retries += 1
        state.total_retries += 1
        state.save(_state_path(mission_id))
        _broadcast_mission_refresh(state)
        self._json({"retrying": True})

    def _post_task_inject(self, mission_id: str, task_id: str, body: dict) -> None:
        state = _load_state(mission_id)
        if not state:
            self._json({"error": f"Mission {mission_id!r} not found"}, status=404)
            return
        task_state = state.task_states.get(task_id)
        if not task_state:
            self._json({"error": f"Task {task_id!r} not found in mission {mission_id!r}"}, status=404)
            return
        if _task_status_value(task_state) != "in_progress":
            self._json({"error": "task not in_progress"}, status=409)
            return
        message = body.get("message")
        if not isinstance(message, str):
            self._json({"error": "message is required"}, status=400)
            return
        inject_path = _inject_path(mission_id, task_id)
        inject_path.parent.mkdir(parents=True, exist_ok=True)
        with open(inject_path, "w", encoding="utf-8") as fh:
            _jsonlib.dump({"message": message, "timestamp": _now_iso()}, fh)
        self._json({"delivered": True})

    def _post_task_resolve(self, mission_id: str, task_id: str, body: dict) -> None:
        state = _load_state(mission_id)
        if not state:
            self._json({"error": f"Mission {mission_id!r} not found"}, status=404)
            return
        task_state = state.task_states.get(task_id)
        if not task_state:
            self._json({"error": f"Task {task_id!r} not found in mission {mission_id!r}"}, status=404)
            return
        if _task_status_value(task_state) != "needs_human":
            self._json({"error": "task not needs_human"}, status=409)
            return
        if body.get("failed"):
            task_state.status = "failed"
            task_state.human_intervention_needed = False
            task_state.human_intervention_message = ""
            task_state.bump()
            state.save(_state_path(mission_id))
            _broadcast_mission_refresh(state)
            self._json({"failed": True})
            return
        message = body.get("message")
        if not isinstance(message, str):
            self._json({"error": "message is required"}, status=400)
            return
        task_state.status = "pending"
        task_state.worker_output = (task_state.worker_output + "\n" + message).strip()
        state.save(_state_path(mission_id))
        _broadcast_mission_refresh(state)
        self._json({"resolved": True})

    def _post_connector_configure(self, name: str, body: dict) -> None:
        token = body.get("token")
        if not isinstance(token, str) or not token:
            self._json({"error": "token is required"}, status=400)
            return
        try:
            import keyring

            keyring.set_password("agentforce", name, token)
        except Exception as exc:
            self._json({"error": str(exc)}, status=500)
            return
        metadata = _load_connectors_metadata()
        metadata[name] = {
            "active": True,
            "last_configured": _now_iso(),
        }
        _save_connectors_metadata(metadata)
        self._json({"configured": True})

    def _post_connector_test(self, name: str) -> None:
        try:
            import keyring

            token = keyring.get_password("agentforce", name)
            _connector_test_request(name, token or "")
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)})
            return
        self._json({"ok": True})

    def _delete_connector(self, name: str) -> None:
        try:
            import keyring

            try:
                keyring.delete_password("agentforce", name)
            except Exception:
                pass
        except Exception as exc:
            self._json({"error": str(exc)}, status=500)
            return
        metadata = _load_connectors_metadata()
        metadata.pop(name, None)
        _save_connectors_metadata(metadata)
        self._json({"deleted": True})


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
