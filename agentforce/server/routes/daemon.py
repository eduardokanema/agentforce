"""Daemon control API routes."""
from __future__ import annotations

import os

from agentforce.server import ws


# ---------------------------------------------------------------------------
# WebSocket broadcast callbacks — wired into MissionDaemon on creation
# ---------------------------------------------------------------------------

def _ws_on_enqueue(event: dict) -> None:
    ws.broadcast(event)


def _ws_on_start(event: dict) -> None:
    ws.broadcast(event)


def _ws_on_complete(event: dict) -> None:
    ws.broadcast(event)


def _ws_on_fail(event: dict) -> None:
    ws.broadcast(event)


def _ws_on_status_changed(event: dict) -> None:
    ws.broadcast(event)


def _get_daemon():
    import agentforce.server.handler as _handler
    return _handler._daemon


def _check_auth(handler) -> bool:
    token = os.environ.get("AGENTFORCE_TOKEN")
    if not token:
        return True
    return handler.headers.get("X-Agentforce-Token") == token


def get(handler, parts, query):
    daemon = _get_daemon()
    if daemon is None:
        return 503, {"error": "daemon not active"}
    raw = daemon.status()
    return 200, {
        "running": raw["running"],
        "queue": list(raw["queue"].values()),
        "active": list(raw["active"].values()),
        "last_heartbeat": raw.get("last_heartbeat"),
    }


def post(handler, parts, query):
    if not _check_auth(handler):
        return 401, {"error": "unauthorized"}
    daemon = _get_daemon()
    if daemon is None:
        return 503, {"error": "daemon not active"}
    action = parts[-1] if parts else None
    body = handler._read_json_body()

    if action == "enqueue":
        mission_id = body.get("mission_id")
        if not mission_id:
            raise ValueError("mission_id required")
        daemon.enqueue(mission_id)
        return 200, {"enqueued": True, "mission_id": mission_id}

    if action == "dequeue":
        mission_id = body.get("mission_id")
        if not mission_id:
            raise ValueError("mission_id required")
        status = daemon.status()
        if mission_id in status["active"]:
            return 409, {"error": "mission is running"}
        daemon.dequeue(mission_id)
        return 200, {"dequeued": True, "mission_id": mission_id}

    if action == "stop":
        import threading
        threading.Thread(target=daemon.stop, daemon=True, name="daemon-stop").start()
        return 200, {"stopping": True}

    if action == "restart":
        import threading
        def _do_restart():
            daemon.stop()
            daemon.start()
        threading.Thread(target=_do_restart, daemon=True, name="daemon-restart").start()
        return 200, {"restarting": True}

    raise FileNotFoundError()
