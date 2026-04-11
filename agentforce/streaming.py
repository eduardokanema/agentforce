"""Structured task streaming primitives."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


def raw_stream_path(mission_id: str, task_id: str, stream_dir: Path | None = None) -> Path:
    root = Path(stream_dir) if stream_dir is not None else Path.home() / ".agentforce" / "streams"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{mission_id}_{task_id}.log"


def event_stream_path(mission_id: str, task_id: str, stream_dir: Path | None = None) -> Path:
    root = Path(stream_dir) if stream_dir is not None else Path.home() / ".agentforce" / "streams"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{mission_id}_{task_id}.events.jsonl"


def event_seq_path(mission_id: str, task_id: str, stream_dir: Path | None = None) -> Path:
    root = Path(stream_dir) if stream_dir is not None else Path.home() / ".agentforce" / "streams"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{mission_id}_{task_id}.events.seq"


def load_stream_events(
    mission_id: str,
    task_id: str,
    after_seq: int = 0,
    stream_dir: Path | None = None,
) -> list[dict[str, Any]]:
    path = event_stream_path(mission_id, task_id, stream_dir)
    if not path.exists():
        return []

    events: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if int(payload.get("seq", 0)) <= after_seq:
                continue
            events.append(payload)
    return events


class StreamRecorder:
    """Shared writer for canonical stream events + raw line log."""

    def __init__(
        self,
        mission_id: str,
        task_id: str,
        provider: str,
        stream_dir: Path | None = None,
        raw_path: Path | None = None,
    ) -> None:
        self.mission_id = mission_id
        self.task_id = task_id
        self.provider = provider
        self.stream_dir = Path(stream_dir) if stream_dir is not None else Path.home() / ".agentforce" / "streams"
        self.stream_dir.mkdir(parents=True, exist_ok=True)
        self.raw_path = raw_path or raw_stream_path(mission_id, task_id, self.stream_dir)
        self.events_path = event_stream_path(mission_id, task_id, self.stream_dir)
        self.seq_path = event_seq_path(mission_id, task_id, self.stream_dir)

    @classmethod
    def from_raw_stream_path(cls, stream_path: Path | None, provider: str) -> "StreamRecorder | None":
        if stream_path is None:
            return None
        stem = Path(stream_path).stem
        idx = stem.find("_")
        if idx < 0:
            return None
        mission_id, task_id = stem[:idx], stem[idx + 1 :]
        return cls(
            mission_id=mission_id,
            task_id=task_id,
            provider=provider,
            stream_dir=Path(stream_path).parent,
            raw_path=Path(stream_path),
        )

    def _next_seq(self) -> int:
        self.seq_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.seq_path, "a+", encoding="utf-8") as fh:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            fh.seek(0)
            current_raw = fh.read().strip()
            current = int(current_raw) if current_raw else 0
            seq = current + 1
            fh.seek(0)
            fh.truncate()
            fh.write(str(seq))
            fh.flush()
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        return seq

    def append_raw_line(self, line: str) -> None:
        if line == "":
            return
        with open(self.raw_path, "a", encoding="utf-8") as fh:
            fh.write(line if line.endswith("\n") else line + "\n")
            fh.flush()

    def append_raw_text(self, text: str) -> None:
        if text == "":
            return
        with open(self.raw_path, "a", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()

    def emit(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        role: str | None = None,
        raw_line: str | None = None,
    ) -> dict[str, Any]:
        event = {
            "seq": self._next_seq(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mission_id": self.mission_id,
            "task_id": self.task_id,
            "provider": self.provider,
            "role": role or "system",
            "kind": kind,
            "payload": payload or {},
        }
        if raw_line is not None:
            event["raw_line"] = raw_line
        with open(self.events_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")
            fh.flush()
        if raw_line:
            self.append_raw_line(raw_line)
        return event

    def status(self, state: str, message: str, *, role: str = "system", raw_line: str | None = None) -> dict[str, Any]:
        return self.emit("status", {"state": state, "message": message}, role=role, raw_line=raw_line)

    def text_delta(self, text: str, *, role: str = "assistant") -> dict[str, Any]:
        raw_line = text if "\n" not in text else None
        event = self.emit("text_delta", {"text": text}, role=role, raw_line=raw_line)
        if raw_line is None:
            self.append_raw_text(text)
        return event

    def tool_start(self, call_id: str, title: str, *, command: str | None = None, role: str = "assistant", raw_line: str | None = None) -> dict[str, Any]:
        return self.emit(
            "tool_start",
            {"call_id": call_id, "title": title, "command": command},
            role=role,
            raw_line=raw_line,
        )

    def tool_output(self, call_id: str, text: str, *, stream: str = "stdout", role: str = "assistant") -> dict[str, Any]:
        return self.emit(
            "tool_output",
            {"call_id": call_id, "text": text, "stream": stream},
            role=role,
        )

    def tool_end(
        self,
        call_id: str,
        *,
        exit_code: int | None = None,
        success: bool | None = None,
        role: str = "assistant",
        raw_line: str | None = None,
    ) -> dict[str, Any]:
        return self.emit(
            "tool_end",
            {"call_id": call_id, "exit_code": exit_code, "success": success},
            role=role,
            raw_line=raw_line,
        )

    def usage(self, *, tokens_in: int, tokens_out: int, cost_usd: float = 0.0, role: str = "system") -> dict[str, Any]:
        return self.emit(
            "usage",
            {"tokens_in": tokens_in, "tokens_out": tokens_out, "cost_usd": cost_usd},
            role=role,
        )

    def warning(self, message: str, *, role: str = "system") -> dict[str, Any]:
        return self.emit("warning", {"message": message}, role=role, raw_line=message)

    def error(self, message: str, *, role: str = "system") -> dict[str, Any]:
        return self.emit("error", {"message": message}, role=role, raw_line=message)

    def user_instruction(self, message: str, *, role: str = "user") -> dict[str, Any]:
        return self.emit("user_instruction", {"message": message}, role=role, raw_line=f"[USER INSTRUCTION] {message}")

    def raw_line(self, text: str, *, role: str = "system", meta: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.emit("raw_line", {"text": text, "meta": meta or {}}, role=role, raw_line=text)
