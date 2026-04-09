from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import socket
import struct
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from agentforce.core.spec import Caps, MissionSpec, TaskSpec
from agentforce.core.state import MissionState, TaskState
from agentforce.server.handler import DashboardHandler


def _set_handler_config(state_dir: Path, port: int = 8080) -> None:
    DashboardHandler.config = DashboardHandler.config.__class__(
        state_dir=Path(state_dir),
        host="localhost",
        port=port,
    )


def _mission_state() -> MissionState:
    spec = MissionSpec(
        name="Integration Mission",
        goal="Exercise the dashboard over HTTP and WebSocket",
        definition_of_done=["Routes respond"],
        tasks=[
            TaskSpec(
                id="task-1",
                title="Check API",
                description="Return JSON mission summaries",
                acceptance_criteria=["GET /api/missions returns JSON"],
            )
        ],
        caps=Caps(max_concurrent_workers=1),
    )
    return MissionState(
        mission_id="mission-123",
        spec=spec,
        task_states={
            "task-1": TaskState(
                task_id="task-1",
                spec_summary="Return JSON mission summaries",
                status="in_progress",
            ),
        },
        started_at="2024-01-01T00:00:00+00:00",
    )


def _start_server(state_dir: Path) -> tuple[ThreadingHTTPServer, threading.Thread, int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, server.server_address[1]


def _read_http_response(sock: socket.socket) -> tuple[str, dict[str, str], bytes]:
    buffer = b""
    while b"\r\n\r\n" not in buffer:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buffer += chunk

    header_bytes, _, body = buffer.partition(b"\r\n\r\n")
    lines = header_bytes.decode("iso-8859-1").split("\r\n")
    status_line = lines[0]
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line or ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()
    return status_line, headers, body


def _read_ws_frame(sock: socket.socket) -> tuple[int, bytes]:
    first_two = sock.recv(2)
    if len(first_two) < 2:
        raise AssertionError("expected websocket frame header")
    first_byte, second_byte = struct.unpack("!BB", first_two)
    opcode = first_byte & 0x0F
    masked = bool(second_byte & 0x80)
    length = second_byte & 0x7F

    if length == 126:
        extended = sock.recv(2)
        if len(extended) < 2:
            raise AssertionError("expected extended websocket length")
        length = struct.unpack("!H", extended)[0]
    elif length == 127:
        extended = sock.recv(8)
        if len(extended) < 8:
            raise AssertionError("expected extended websocket length")
        length = struct.unpack("!Q", extended)[0]

    if masked:
        mask = sock.recv(4)
        if len(mask) < 4:
            raise AssertionError("expected websocket mask")
    payload = b""
    while len(payload) < length:
        chunk = sock.recv(length - len(payload))
        if not chunk:
            raise AssertionError("expected websocket payload")
        payload += chunk
    return opcode, payload


def test_dashboard_integration_http_and_websocket(tmp_path: Path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    _mission_state().save(state_dir / "mission-123.json")
    _set_handler_config(state_dir)

    server, thread, port = _start_server(state_dir)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)

        conn.request("GET", "/api/missions")
        response = conn.getresponse()
        missions = json.loads(response.read().decode("utf-8"))
        assert response.status == 200
        assert isinstance(missions, list)
        assert missions and missions[0]["mission_id"] == "mission-123"

        conn.request("GET", "/")
        response = conn.getresponse()
        html = response.read().decode("utf-8")
        assert response.status == 200
        assert response.getheader("Content-Type", "").startswith("text/html")
        assert "<!doctype html>" in html.lower()

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        expected_accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("utf-8")).digest()
        ).decode("ascii")

        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            request = (
                "GET /ws HTTP/1.1\r\n"
                "Host: 127.0.0.1\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode("ascii")
            sock.sendall(request)

            status_line, headers, _ = _read_http_response(sock)
            assert status_line.startswith("HTTP/1.0 101")
            assert headers["sec-websocket-accept"] == expected_accept

            payload = b"hi"
            mask = b"abcd"
            masked_payload = bytes(payload[i] ^ mask[i % 4] for i in range(len(payload)))
            frame = bytearray([0x89, 0x80 | len(payload)])
            frame.extend(mask)
            frame.extend(masked_payload)
            sock.sendall(frame)

            opcode, pong_payload = _read_ws_frame(sock)
            assert opcode == 0x0A
            assert pong_payload == payload
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
