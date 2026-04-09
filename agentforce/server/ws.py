"""Stdlib WebSocket support for the AgentForce dashboard."""
from __future__ import annotations

import base64
import hashlib
import json
import struct
import threading
from typing import Any

_WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

_LOCK = threading.Lock()
_SUBSCRIBERS: dict[str, set["WsConnection"]] = {}


def _ws_handshake(handler) -> bool:
    """Perform the RFC 6455 handshake for an HTTP upgrade request."""
    headers = handler.headers
    key = None
    if headers is not None:
        key = headers.get("Sec-WebSocket-Key")
        if key is None:
            key = headers.get("sec-websocket-key")
        if key is None and hasattr(headers, "items"):
            for header_name, header_value in headers.items():
                if header_name.lower() == "sec-websocket-key":
                    key = header_value
                    break
    if not key:
        return False

    accept = base64.b64encode(
        hashlib.sha1((key + _WS_MAGIC).encode("utf-8")).digest()
    ).decode("ascii")

    handler.send_response(101)
    handler.send_header("Upgrade", "websocket")
    handler.send_header("Connection", "Upgrade")
    handler.send_header("Sec-WebSocket-Accept", accept)
    handler.end_headers()
    return True


def handshake(handler) -> bool:
    """Public alias used by higher-level websocket routing."""
    return _ws_handshake(handler)


class WsConnection:
    """Wrap a raw socket with minimal RFC 6455 framing."""

    def __init__(self, sock: Any):
        self.socket = sock

    def _read_exact(self, size: int) -> bytes | None:
        chunks: list[bytes] = []
        remaining = size
        while remaining > 0:
            chunk = self.socket.recv(remaining)
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def send_text(self, msg: str) -> None:
        payload = msg.encode("utf-8")
        length = len(payload)

        header = bytearray()
        header.append(0x81)  # FIN=1, opcode=1

        if length <= 125:
            header.append(length)
        elif length <= 0xFFFF:
            header.append(126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(127)
            header.extend(struct.pack("!Q", length))

        self.socket.sendall(bytes(header) + payload)

    def send_pong(self, payload: bytes = b"") -> None:
        if len(payload) > 125:
            payload = payload[:125]
        self.socket.sendall(bytes([0x8A, len(payload)]) + payload)

    def _recv_frame(self) -> tuple[int, bytes] | None:
        try:
            header = self._read_exact(2)
            if header is None:
                return None

            first_byte, second_byte = struct.unpack("!BB", header)
            opcode = first_byte & 0x0F
            masked = bool(second_byte & 0x80)
            length = second_byte & 0x7F

            if opcode == 0x8:
                return None
            if opcode not in (0x1, 0x9):
                return None
            if not masked:
                return None

            if length == 126:
                ext = self._read_exact(2)
                if ext is None:
                    return None
                length = struct.unpack("!H", ext)[0]
            elif length == 127:
                ext = self._read_exact(8)
                if ext is None:
                    return None
                length = struct.unpack("!Q", ext)[0]

            masking_key = self._read_exact(4)
            if masking_key is None:
                return None

            payload = self._read_exact(length)
            if payload is None:
                return None

            unmasked = bytes(
                payload[i] ^ masking_key[i % 4] for i in range(len(payload))
            )
            return opcode, unmasked
        except (OSError, struct.error, UnicodeDecodeError, ValueError):
            return None

    def recv_text(self) -> str | None:
        frame = self._recv_frame()
        if frame is None:
            return None

        opcode, payload = frame
        if opcode == 0x9:
            self.send_pong(payload)
            return ""

        if opcode != 0x1:
            return None

        return payload.decode("utf-8")

    def close(self) -> None:
        try:
            self.socket.sendall(b"\x88\x00")
        except OSError:
            pass
        finally:
            try:
                self.socket.close()
            except OSError:
                pass


def register(conn: WsConnection, mission_id: str = "*") -> None:
    with _LOCK:
        _SUBSCRIBERS.setdefault(mission_id, set()).add(conn)


def unregister(conn: WsConnection, mission_id: str = "*") -> None:
    with _LOCK:
        for key, subscribers in list(_SUBSCRIBERS.items()):
            if mission_id != "*" and key != mission_id:
                continue
            subscribers.discard(conn)
            if not subscribers:
                del _SUBSCRIBERS[key]


def _subscriber_snapshot(mission_id: str) -> set[WsConnection]:
    with _LOCK:
        return set(_SUBSCRIBERS.get(mission_id, set()))


def _drop_dead_connection(conn: WsConnection) -> None:
    with _LOCK:
        for key, subscribers in list(_SUBSCRIBERS.items()):
            subscribers.discard(conn)
            if not subscribers:
                del _SUBSCRIBERS[key]


def _broadcast_to_subscribers(
    mission_id: str, message: str, subscribers: set[WsConnection] | None = None
) -> None:
    targets = subscribers if subscribers is not None else _subscriber_snapshot(mission_id)
    for conn in targets:
        try:
            conn.send_text(message)
        except OSError:
            unregister(conn, mission_id)
            _drop_dead_connection(conn)


def broadcast_mission_list(summaries: list[dict]) -> None:
    message = json.dumps({"type": "mission_list", "missions": summaries})
    _broadcast_to_subscribers("*", message)


def broadcast_mission(mission_id: str, state_dict: dict) -> None:
    message = json.dumps(
        {"type": "mission_state", "mission_id": mission_id, "state": state_dict}
    )
    _broadcast_to_subscribers(mission_id, message)


def broadcast_stream_line(mission_id: str, task_id: str, line: str, seq: int) -> None:
    message = json.dumps(
        {
            "type": "stream_line",
            "mission_id": mission_id,
            "task_id": task_id,
            "line": line,
            "seq": seq,
        }
    )
    _broadcast_to_subscribers(mission_id, message)


def broadcast_task_stream_done(mission_id: str, task_id: str) -> None:
    message = json.dumps(
        {
            "type": "task_stream_done",
            "mission_id": mission_id,
            "task_id": task_id,
        }
    )
    _broadcast_to_subscribers(mission_id, message)


def broadcast_mission_cost_update(
    mission_id: str, tokens_in: int, tokens_out: int, cost_usd: float
) -> None:
    message = json.dumps(
        {
            "type": "mission_cost_update",
            "mission_id": mission_id,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
        }
    )
    _broadcast_to_subscribers(mission_id, message)


def broadcast_task_cost_update(
    mission_id: str, task_id: str, tokens_in: int, tokens_out: int, cost_usd: float
) -> None:
    message = json.dumps(
        {
            "type": "task_cost_update",
            "mission_id": mission_id,
            "task_id": task_id,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
        }
    )
    _broadcast_to_subscribers(mission_id, message)


def broadcast_task_attempt_start(mission_id: str, task_id: str, attempt_number: int) -> None:
    message = json.dumps(
        {
            "type": "task_attempt_start",
            "mission_id": mission_id,
            "task_id": task_id,
            "attempt_number": attempt_number,
        }
    )
    _broadcast_to_subscribers(mission_id, message)
