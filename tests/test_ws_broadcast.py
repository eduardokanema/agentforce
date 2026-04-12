from __future__ import annotations

import builtins
import threading
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from agentforce.core.event_bus import EVENT_BUS
from agentforce.core.engine import MissionEngine
from agentforce.core.spec import Caps, MissionSpec, TaskSpec
from agentforce.memory import Memory
from agentforce.server.handler import DashboardHandler, serve
from agentforce.server.watchers import _watch_state_dir


def make_engine(tmp_path: Path) -> MissionEngine:
    spec = MissionSpec(
        name="Broadcast Mission",
        goal="Exercise websocket broadcasts",
        definition_of_done=["Done"],
        tasks=[TaskSpec(id="task-1", title="Task 1", description="First task", acceptance_criteria=["assert output == 'ok'"])],
        caps=Caps(max_concurrent_workers=1, max_retries_global=3, max_wall_time_minutes=60),
    )
    state_dir = tmp_path / "state"
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    return MissionEngine(spec=spec, state_dir=state_dir, memory=Memory(memory_dir))


def make_handler() -> DashboardHandler:
    handler = object.__new__(DashboardHandler)
    handler.path = "/mission/mission-1/task/task-1/stream"
    handler.headers = {}
    handler.connection = object()
    handler.wfile = BytesIO()
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    return handler


def test_engine_save_broadcasts_mission_state_and_summary(tmp_path):
    engine = make_engine(tmp_path)

    with patch.object(EVENT_BUS, "publish") as publish:
        engine._save()

    assert call(
        "mission.snapshot",
        {"mission_id": engine.state.mission_id, "state": engine.state.to_dict()},
    ) in publish.call_args_list
    assert call(
        "mission.list_snapshot",
        {"missions": [engine.state.to_summary_dict()]},
    ) in publish.call_args_list


def test_engine_save_swallows_ws_import_failure(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "agentforce.server" or name == "agentforce.server.ws":
            raise ImportError("boom")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    engine._save()


def test_sse_broadcasts_stream_lines_with_incrementing_sequence(tmp_path):
    handler = make_handler()
    streams_dir = tmp_path / "streams"
    streams_dir.mkdir(parents=True, exist_ok=True)
    stream_file = streams_dir / "mission-1_task-1.log"
    stream_file.write_text("first\nsecond\n", encoding="utf-8")

    terminal_state = SimpleNamespace(
        task_states={"task-1": SimpleNamespace(status="review_approved")}
    )

    with patch("agentforce.server.handler._STREAMS_DIR", streams_dir), \
            patch("agentforce.server.handler._load_state", return_value=terminal_state), \
            patch("agentforce.server.ws.broadcast_stream_line") as broadcast_stream_line, \
            patch("agentforce.server.ws.broadcast_task_stream_done") as broadcast_task_stream_done:
        handler._sse("mission-1", "task-1")

    assert broadcast_stream_line.call_args_list == [
        call("mission-1", "task-1", "first", 1),
        call("mission-1", "task-1", "second", 2),
    ]
    broadcast_task_stream_done.assert_called_once_with("mission-1", "task-1")


def test_serve_starts_daemon_watchdog_thread(monkeypatch):
    server_instance = MagicMock()
    server_instance.serve_forever.side_effect = KeyboardInterrupt

    thread_ctor = MagicMock()
    thread_instance = MagicMock()
    thread_ctor.return_value = thread_instance

    monkeypatch.setattr("agentforce.server.handler.ThreadingHTTPServer", MagicMock(return_value=server_instance))
    monkeypatch.setattr("agentforce.server.handler.threading.Thread", thread_ctor)

    serve(port=8123)

    assert thread_ctor.call_count >= 1
    # Verify the state-watchdog thread was started with daemon=True
    watchdog_calls = [c for c in thread_ctor.call_args_list if c.kwargs.get("name") == "agentforce-state-watchdog"]
    assert len(watchdog_calls) == 1
    assert watchdog_calls[0].kwargs["daemon"] is True


def test_watchdog_broadcasts_mission_list_when_state_files_change(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    spec = MissionSpec(
        name="Watchdog Mission",
        goal="Watch state dir",
        definition_of_done=["Done"],
        tasks=[TaskSpec(id="task-1", title="Task 1", description="First task", acceptance_criteria=["assert output == 'ok'"])],
        caps=Caps(max_concurrent_workers=1, max_retries_global=3, max_wall_time_minutes=60),
    )
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    engine = MissionEngine(spec=spec, state_dir=state_dir, memory=Memory(memory_dir))
    state_file = engine.state_file

    sleep_calls = []
    stop_event = threading.Event()

    def fake_sleep(_seconds):
        sleep_calls.append(_seconds)
        if len(sleep_calls) == 1:
            state_file.touch()
        else:
            stop_event.set()

    monkeypatch.setattr("agentforce.server.watchers._time.sleep", fake_sleep)

    with patch("agentforce.server.ws.broadcast_mission_list") as broadcast_mission_list:
        _watch_state_dir(state_dir=state_dir, stop_event=stop_event, poll_seconds=0.01)

    broadcast_mission_list.assert_called_once()
    assert broadcast_mission_list.call_args.args[0] == [engine.state.to_summary_dict()]
