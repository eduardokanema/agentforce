"""Tests for MissionDaemon core behavior."""
from __future__ import annotations

import fcntl
import multiprocessing
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from agentforce.daemon import DaemonAlreadyRunning, DaemonCallbacks, DaemonLock, MissionDaemon


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slow_run(delay: float = 1.0):
    """Returns a callable that sleeps, simulating run_autonomous."""
    def _run(mission_id: str, **kwargs):
        time.sleep(delay)
    return _run


@pytest.fixture
def daemon(tmp_path):
    d = MissionDaemon(
        state_dir=tmp_path,
        max_concurrent=2,
        max_drain_seconds=1,
        poll_interval=0.05,
    )
    yield d
    if d.status()["running"]:
        d.stop()


# ---------------------------------------------------------------------------
# Core tests (matched by -k 'core')
# ---------------------------------------------------------------------------

def test_core_enqueue_status(daemon):
    """After enqueue, mission appears in status()['queue'] with state='queued'."""
    daemon.enqueue("m-001")
    s = daemon.status()
    assert "m-001" in s["queue"]
    assert s["queue"]["m-001"]["state"] == "queued"


def test_core_dequeue(daemon):
    """dequeue removes a queued mission from status()['queue']."""
    daemon.enqueue("m-002")
    daemon.dequeue("m-002")
    assert "m-002" not in daemon.status()["queue"]


def test_core_running_state(daemon):
    """After start() picks up a mission, it appears in status()['active'] with state='running'."""
    with patch("agentforce.daemon.run_autonomous", side_effect=_slow_run(5.0)):
        daemon.enqueue("m-003")
        daemon.start()
        time.sleep(0.3)
        s = daemon.status()
        assert "m-003" in s["active"]
        assert s["active"]["m-003"]["state"] == "running"


def test_core_max_concurrent(tmp_path):
    """3 missions with max_concurrent=2 → len(active) <= 2 at any point."""
    d = MissionDaemon(
        state_dir=tmp_path,
        max_concurrent=2,
        max_drain_seconds=1,
        poll_interval=0.05,
    )
    try:
        with patch("agentforce.daemon.run_autonomous", side_effect=_slow_run(5.0)):
            for i in range(3):
                d.enqueue(f"m-{i:03d}")
            d.start()
            time.sleep(0.3)
            s = d.status()
            assert len(s["active"]) <= 2
    finally:
        d.stop()


def test_core_stop(daemon):
    """stop() returns and status()['running'] is False afterwards."""
    with patch("agentforce.daemon.run_autonomous", side_effect=_slow_run(0.05)):
        daemon.start()
        assert daemon.status()["running"] is True
        daemon.stop()
        assert daemon.status()["running"] is False


def test_core_queue_persistence(tmp_path):
    """daemon_queue.jsonl exists after enqueue; a new daemon restores the queue."""
    d1 = MissionDaemon(state_dir=tmp_path, max_concurrent=2, poll_interval=0.05)
    d1.enqueue("m-persist")

    jsonl = tmp_path / "daemon_queue.jsonl"
    assert jsonl.exists(), "JSONL file must be created on enqueue"

    # New daemon with same state_dir — no start(), just check queue restoration
    d2 = MissionDaemon(state_dir=tmp_path, max_concurrent=2, poll_interval=0.05)
    s = d2.status()
    assert "m-persist" in s["queue"]
    assert s["queue"]["m-persist"]["state"] == "queued"


def test_core_pause_on_stop(tmp_path):
    """stop() pauses in-flight missions via pause_mission() when drain timeout expires."""
    d = MissionDaemon(
        state_dir=tmp_path,
        max_concurrent=2,
        max_drain_seconds=0.3,
        poll_interval=0.05,
    )
    paused_ids: list[str] = []

    def fake_pause(mission_id: str) -> None:
        paused_ids.append(mission_id)

    with patch("agentforce.daemon.run_autonomous", side_effect=_slow_run(30.0)), \
         patch("agentforce.daemon.pause_mission", side_effect=fake_pause):
        d.enqueue("m-long")
        d.start()
        time.sleep(0.2)  # let supervisor dispatch it
        assert "m-long" in d.status()["active"]
        d.stop()
        assert "m-long" in paused_ids, "pause_mission must be called for in-flight mission"


# ---------------------------------------------------------------------------
# Lock tests (matched by -k 'lock')
# ---------------------------------------------------------------------------

def test_lock_exclusive_raises(tmp_path):
    """Second MissionDaemon.start() raises DaemonAlreadyRunning when lock is held."""
    d1 = MissionDaemon(state_dir=tmp_path, max_concurrent=1, poll_interval=0.05)
    d2 = MissionDaemon(state_dir=tmp_path, max_concurrent=1, poll_interval=0.05)

    with patch("agentforce.daemon.run_autonomous", side_effect=_slow_run(5.0)):
        d1.start()
        try:
            with pytest.raises(DaemonAlreadyRunning):
                d2.start()
        finally:
            d1.stop()


def test_lock_released_on_stop(tmp_path):
    """daemon.lock is released (fcntl LOCK_EX|LOCK_NB succeeds) after daemon.stop()."""
    lock_path = tmp_path / "daemon.lock"
    d = MissionDaemon(state_dir=tmp_path, max_concurrent=1, poll_interval=0.05)

    with patch("agentforce.daemon.run_autonomous", side_effect=_slow_run(5.0)):
        d.start()
        d.stop()

    # Lock must be free after stop()
    fh = lock_path.open("w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # must not raise
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()


def _hold_lock_forever(lock_path_str: str, ready_event) -> None:
    """Worker: open the lock file, acquire LOCK_EX, signal ready, then sleep."""
    fh = open(lock_path_str, "w")  # noqa: WPS515
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    fh.write(str(os.getpid()))
    fh.flush()
    ready_event.set()
    time.sleep(300)  # held until process is killed


def test_lock_released_on_process_death(tmp_path):
    """OS releases daemon.lock after the holding process is killed with SIGKILL."""
    lock_path = tmp_path / "daemon.lock"
    ready = multiprocessing.Event()

    p = multiprocessing.Process(
        target=_hold_lock_forever,
        args=(str(lock_path), ready),
        daemon=True,
    )
    p.start()
    assert ready.wait(timeout=5), "worker process never signalled ready"

    # Verify we cannot acquire the lock while the process is alive
    fh_check = lock_path.open("w")
    try:
        with pytest.raises((BlockingIOError, OSError)):
            fcntl.flock(fh_check.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        fh_check.close()

    # Kill the process with SIGKILL (no cleanup)
    os.kill(p.pid, 9)
    p.join(timeout=5)

    # Lock must now be free
    fh_after = lock_path.open("w")
    try:
        fcntl.flock(fh_after.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fh_after.fileno(), fcntl.LOCK_UN)
    finally:
        fh_after.close()


def test_lock_concurrent_journal_writes(tmp_path):
    """10 concurrent _append_journal calls produce exactly 10 valid JSON lines."""
    d = MissionDaemon(state_dir=tmp_path, max_concurrent=1, poll_interval=0.05)
    errors: list[Exception] = []
    threads = []

    def write_entry(i: int) -> None:
        try:
            d._append_journal({"action": "test", "seq": i})
        except Exception as exc:
            errors.append(exc)

    for i in range(10):
        t = threading.Thread(target=write_entry, args=(i,))
        threads.append(t)

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"journal write raised: {errors}"

    lines = (tmp_path / "daemon_queue.jsonl").read_text().splitlines()
    assert len(lines) == 10, f"expected 10 lines, got {len(lines)}"
    for line in lines:
        import json
        rec = json.loads(line)  # must parse as valid JSON
        assert rec["action"] == "test"


# ---------------------------------------------------------------------------
# CLI / Detached process tests (matched by -k 'detached or cli')
# ---------------------------------------------------------------------------

def _daemon_env(tmp_path) -> dict:
    """Build an env dict that points AGENTFORCE_STATE_DIR at tmp_path."""
    return {**os.environ, "AGENTFORCE_STATE_DIR": str(tmp_path)}


def _start_daemon(tmp_path) -> int:
    """Run 'python3 -m agentforce.daemon start' and return the daemon pid."""
    result = subprocess.run(
        [sys.executable, "-m", "agentforce.daemon", "start"],
        capture_output=True,
        text=True,
        env=_daemon_env(tmp_path),
    )
    assert result.returncode == 0, f"start failed: {result.stderr}"
    pid_file = tmp_path / "daemon.pid"
    assert pid_file.exists(), "daemon.pid not created"
    return int(pid_file.read_text().strip())


def test_cli_start_creates_pid_file(tmp_path):
    """python3 -m agentforce.daemon start creates daemon.pid with a live pid."""
    pid = _start_daemon(tmp_path)
    try:
        assert pid > 0
        os.kill(pid, 0)  # must not raise — process is alive
    finally:
        os.kill(pid, signal.SIGTERM)
        time.sleep(0.5)


def test_cli_stop_removes_pid_file(tmp_path):
    """After stop, daemon.pid does not exist and the process is dead."""
    env = _daemon_env(tmp_path)
    pid = _start_daemon(tmp_path)

    result = subprocess.run(
        [sys.executable, "-m", "agentforce.daemon", "stop"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, f"stop failed: {result.stderr}"

    pid_file = tmp_path / "daemon.pid"
    assert not pid_file.exists(), "daemon.pid should be removed after stop"

    time.sleep(0.3)
    with pytest.raises((ProcessLookupError, OSError)):
        os.kill(pid, 0)


def test_cli_status_running_and_stopped(tmp_path):
    """status prints 'running' while alive, 'stopped' after the process is gone."""
    env = _daemon_env(tmp_path)
    pid = _start_daemon(tmp_path)

    try:
        result = subprocess.run(
            [sys.executable, "-m", "agentforce.daemon", "status"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert "running" in result.stdout.lower(), f"expected 'running' in: {result.stdout}"
    finally:
        os.kill(pid, signal.SIGTERM)
        time.sleep(0.5)

    result = subprocess.run(
        [sys.executable, "-m", "agentforce.daemon", "status"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert "stopped" in result.stdout.lower(), f"expected 'stopped' in: {result.stdout}"


def test_detached_conflicts_with_embedded(tmp_path):
    """Embedded MissionDaemon blocks CLI start; returncode != 0, message has 'already running'."""
    env = _daemon_env(tmp_path)
    d = MissionDaemon(state_dir=tmp_path, max_concurrent=1, poll_interval=0.05)
    with patch("agentforce.daemon.run_autonomous", side_effect=_slow_run(5.0)):
        d.start()
        try:
            result = subprocess.run(
                [sys.executable, "-m", "agentforce.daemon", "start"],
                capture_output=True,
                text=True,
                env=env,
            )
            assert result.returncode != 0
            combined = (result.stdout + result.stderr).lower()
            assert "already running" in combined, f"Expected 'already running' in: {combined!r}"
        finally:
            d.stop()


def test_cli_log_file_rotating_handler(tmp_path):
    """daemon.log exists after start; _setup_logging returns a correctly configured handler."""
    from logging.handlers import RotatingFileHandler
    from agentforce.daemon import _setup_logging

    handler = _setup_logging(tmp_path)
    try:
        assert isinstance(handler, RotatingFileHandler)
        assert handler.maxBytes == 10 * 1024 * 1024  # 10 MB
        assert handler.backupCount >= 3
        assert (tmp_path / "daemon.log").exists()
    finally:
        handler.close()


# ---------------------------------------------------------------------------
# Embedded mode tests (matched by -k 'embedded')
# ---------------------------------------------------------------------------

_MINIMAL_YAML = """\
name: Embedded Test Mission
goal: Verify embedded daemon mode
definition_of_done:
  - done
tasks:
  - id: task-01
    title: Only task
    description: placeholder
"""


def test_embedded_daemon_module_ref(tmp_path, monkeypatch):
    """serve(daemon=True) sets agentforce.server.handler._daemon to a non-None MissionDaemon."""
    from http.server import ThreadingHTTPServer
    import agentforce.server.handler as h

    monkeypatch.setattr(MissionDaemon, "start", lambda self: None)
    monkeypatch.setattr(ThreadingHTTPServer, "serve_forever", lambda self: None)

    h.serve(port=0, state_dir=tmp_path, daemon=True)
    assert h._daemon is not None


def test_embedded_sigint_handler(tmp_path, monkeypatch):
    """SIGINT handler calls daemon.stop() and server.shutdown(); daemon.status()['running'] == False."""
    from http.server import ThreadingHTTPServer
    import agentforce.server.handler as h

    stop_calls: list = []
    shutdown_calls: list = []
    installed: dict = {}

    monkeypatch.setattr(MissionDaemon, "start", lambda self: None)
    monkeypatch.setattr(MissionDaemon, "stop", lambda self: stop_calls.append(True))

    def capture_signal(sig, fn):
        installed[sig] = fn

    monkeypatch.setattr(signal, "signal", capture_signal)

    def fake_serve_forever(self):
        handler_fn = installed.get(signal.SIGINT)
        if handler_fn:
            handler_fn(signal.SIGINT, None)

    monkeypatch.setattr(ThreadingHTTPServer, "serve_forever", fake_serve_forever)
    monkeypatch.setattr(ThreadingHTTPServer, "shutdown", lambda self: shutdown_calls.append(True))

    h.serve(port=0, state_dir=tmp_path, daemon=True)

    assert stop_calls, "daemon.stop() must be called on SIGINT"
    assert shutdown_calls, "server.shutdown() must be called on SIGINT"
    assert h._daemon.status()["running"] is False


def test_embedded_post_missions_enqueues(tmp_path, monkeypatch):
    """POST /api/missions enqueues mission_id into daemon when daemon is active."""
    import agentforce.server.handler as h
    import agentforce.server.routes.missions as m_routes
    from agentforce.server import state_io

    monkeypatch.setattr(state_io, "_STATE_DIR_OVERRIDE", tmp_path)
    daemon = MissionDaemon(state_dir=tmp_path, max_concurrent=1, poll_interval=0.05)
    monkeypatch.setattr(h, "_daemon", daemon)

    status_code, body = m_routes._post_missions({"yaml": _MINIMAL_YAML})

    assert status_code == 200
    assert body.get("status") == "started"
    assert body.get("id") is not None
    assert body["id"] in daemon.status()["queue"]


def test_embedded_post_missions_spawns_thread(tmp_path, monkeypatch):
    """POST /api/missions spawns a thread with 'agentforce-mission-' prefix when daemon is None."""
    import agentforce.server.handler as h
    import agentforce.server.routes.missions as m_routes
    from agentforce.server import state_io

    monkeypatch.setattr(state_io, "_STATE_DIR_OVERRIDE", tmp_path)
    monkeypatch.setattr(h, "_daemon", None)

    spawned: list[threading.Thread] = []
    original_start = threading.Thread.start

    def capture_start(self):
        spawned.append(self)
        original_start(self)

    monkeypatch.setattr(threading.Thread, "start", capture_start)

    with patch("agentforce.autonomous.run_autonomous", return_value=None):
        status_code, body = m_routes._post_missions({"yaml": _MINIMAL_YAML})

    assert status_code == 200
    assert body.get("status") == "started"
    mission_threads = [t for t in spawned if t.name.startswith("agentforce-mission-")]
    assert mission_threads, "Expected a thread named 'agentforce-mission-*' to be started"


# ---------------------------------------------------------------------------
# WebSocket broadcast tests (matched by -k 'websocket or broadcast')
# ---------------------------------------------------------------------------

def test_websocket_on_enqueue_callback(tmp_path):
    """on_enqueue receives {"type": "daemon:enqueued", "mission_id": ...} after enqueue()."""
    received = []
    d = MissionDaemon(
        state_dir=tmp_path,
        callbacks=DaemonCallbacks(on_enqueue=received.append),
        poll_interval=0.05,
    )
    d.enqueue("m-ws-001")
    assert len(received) == 1
    assert received[0] == {"type": "daemon:enqueued", "mission_id": "m-ws-001"}


def test_websocket_on_start_callback(tmp_path):
    """on_start receives {"type": "daemon:started", "mission_id": ...} when mission begins."""
    started = []
    d = MissionDaemon(
        state_dir=tmp_path,
        callbacks=DaemonCallbacks(on_start=started.append),
        poll_interval=0.05,
        max_drain_seconds=1,
    )
    with patch("agentforce.daemon.run_autonomous", side_effect=_slow_run(0.5)):
        d.enqueue("m-ws-002")
        d.start()
        time.sleep(0.2)
        assert len(started) == 1
        assert started[0] == {"type": "daemon:started", "mission_id": "m-ws-002"}
    d.stop()


def test_websocket_on_complete_callback(tmp_path):
    """on_complete receives {"type": "daemon:completed", "mission_id": ...} on success."""
    completed = []
    d = MissionDaemon(
        state_dir=tmp_path,
        callbacks=DaemonCallbacks(on_complete=completed.append),
        poll_interval=0.05,
        max_drain_seconds=1,
    )
    with patch("agentforce.daemon.run_autonomous", return_value=None):
        d.enqueue("m-ws-003")
        d.start()
        time.sleep(0.3)
        assert len(completed) == 1
        assert completed[0] == {"type": "daemon:completed", "mission_id": "m-ws-003"}
    d.stop()


def test_websocket_on_fail_callback(tmp_path):
    """on_fail receives {"type": "daemon:failed", "error": ..., "mission_id": ...} on failure."""
    failed = []
    d = MissionDaemon(
        state_dir=tmp_path,
        callbacks=DaemonCallbacks(on_fail=failed.append),
        poll_interval=0.05,
        max_drain_seconds=1,
    )
    with patch("agentforce.daemon.run_autonomous", side_effect=RuntimeError("boom")):
        d.enqueue("m-ws-004")
        d.start()
        time.sleep(0.3)
        assert len(failed) == 1
        assert failed[0]["type"] == "daemon:failed"
        assert failed[0]["mission_id"] == "m-ws-004"
        assert "error" in failed[0]
    d.stop()


def test_websocket_on_status_changed_callback(tmp_path):
    """on_status_changed fires with running=True on start() and running=False on stop()."""
    events = []
    d = MissionDaemon(
        state_dir=tmp_path,
        callbacks=DaemonCallbacks(on_status_changed=events.append),
        poll_interval=0.05,
        max_drain_seconds=1,
    )
    with patch("agentforce.daemon.run_autonomous", side_effect=_slow_run(0.05)):
        d.start()
        d.stop()
    assert len(events) == 2
    assert events[0] == {"type": "daemon:status_changed", "running": True}
    assert events[1] == {"type": "daemon:status_changed", "running": False}


def test_broadcast_wired_in_daemon_routes(tmp_path, monkeypatch):
    """routes/daemon.py defines _ws_on_enqueue that calls ws.broadcast(); daemon.py has no ws import."""
    import importlib.util
    import agentforce.server.ws as ws
    from agentforce.server.routes import daemon as daemon_routes

    broadcasts = []
    monkeypatch.setattr(ws, "broadcast", lambda payload: broadcasts.append(payload))

    d = MissionDaemon(
        state_dir=tmp_path,
        callbacks=DaemonCallbacks(on_enqueue=daemon_routes._ws_on_enqueue),
        poll_interval=0.05,
    )
    d.enqueue("m-ws-005")

    assert len(broadcasts) == 1
    assert broadcasts[0] == {"type": "daemon:enqueued", "mission_id": "m-ws-005"}

    # Verify daemon.py does not import ws directly
    source = importlib.util.find_spec("agentforce.daemon").origin
    with open(source) as fh:
        content = fh.read()
    assert "import ws" not in content, "daemon.py must not import ws directly"


# ---------------------------------------------------------------------------
# Integration / E2E tests (matched by -k 'integration or e2e')
# ---------------------------------------------------------------------------

# A draft_spec that passes MissionSpec.validate(stage="launch")
_LAUNCHABLE_DRAFT_SPEC = {
    "name": "Integration Test Mission",
    "goal": "Verify draft-to-daemon pipeline works end-to-end",
    "working_dir": None,
    "definition_of_done": ["All pipeline stages complete without error"],
    "tasks": [
        {
            "id": "task-01",
            "title": "Integration task",
            "description": "Verify end-to-end integration of all pipeline stages",
            "acceptance_criteria": ["All stages complete without error"],
        }
    ],
    "caps": {},
}


def test_e2e_draft_to_daemon_execution(tmp_path, monkeypatch):
    """Full flow: create draft → planner turn → patch spec → start → state file + daemon queue.

    Uses DeterministicPlannerAdapter — no HTTP calls to openrouter.ai or api.anthropic.com.
    """
    import json
    from io import BytesIO
    from unittest.mock import MagicMock

    import agentforce.server.handler as h
    import agentforce.server.planner_adapter as pa
    from agentforce.server import state_io
    from agentforce.server.routes import daemon as daemon_routes
    from agentforce.server.routes import plan as plan_routes

    # Isolate all I/O to tmp_path
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(state_io, "AGENTFORCE_HOME", tmp_path)
    monkeypatch.setattr(state_io, "_STATE_DIR_OVERRIDE", state_dir)
    monkeypatch.setattr(pa, "get_planner_adapter", lambda: pa.DeterministicPlannerAdapter())

    # Wire up daemon (not started — we only verify enqueue, not actual execution)
    daemon_inst = MissionDaemon(state_dir=state_dir, max_concurrent=1, poll_interval=0.05)
    monkeypatch.setattr(plan_routes, "_active_daemon", daemon_inst)
    monkeypatch.setattr(h, "_daemon", daemon_inst)

    # Guard: ensure no live HTTP calls reach LLM providers
    import urllib.request as _urlreq
    def _no_live_llm(url, *a, **kw):
        assert "openrouter.ai" not in str(url) and "api.anthropic.com" not in str(url), \
            f"Unexpected HTTP call to LLM endpoint: {url}"
        raise AssertionError(f"urlopen called unexpectedly: {url}")
    monkeypatch.setattr(_urlreq, "urlopen", _no_live_llm)

    # Step 1: POST /api/plan/drafts — create a draft
    code, body = plan_routes._create_draft({"prompt": "Build integration feature X"})
    assert code == 200, f"_create_draft failed: {code} {body}"
    draft_id = body["id"]

    # Step 2: Verify auto-generated draft_spec has name, goal, working_dir
    draft = plan_routes._load_draft(draft_id)
    assert draft is not None
    assert draft.draft_spec.get("goal") != "", "draft_spec.goal must not be empty"
    assert draft.draft_spec.get("name"), "draft_spec.name must be set"
    assert "working_dir" in draft.draft_spec

    # Step 3: POST /api/plan/drafts/:id/messages — one planner turn (deterministic)
    mock_handler = MagicMock()
    mock_handler.wfile = BytesIO()
    code, _ = plan_routes._stream_turn(
        mock_handler, draft_id, {"content": "Proceed with planning"}
    )
    assert code == 200, f"_stream_turn failed: {code}"

    # Patch spec to add a launchable task (DeterministicPlannerAdapter omits tasks)
    draft = plan_routes._load_draft(draft_id)
    code, _ = plan_routes._patch_spec(draft_id, {
        "expected_revision": draft.revision,
        "draft_spec": {**draft.draft_spec, **_LAUNCHABLE_DRAFT_SPEC},
    })
    assert code == 200, f"_patch_spec failed: {code}"

    # Step 4: POST /api/plan/drafts/:id/start
    code, start_body = plan_routes._start_draft(draft_id)
    assert code == 200, f"_start_draft failed: {code} {start_body}"
    mission_id = start_body["mission_id"]
    assert mission_id, "mission_id must be non-empty"

    # Step 5: Mission state file must exist
    state_file = state_dir / f"{mission_id}.json"
    assert state_file.exists(), f"Expected state file at {state_file}"

    # Step 6: Draft must be finalized (GET /api/plan/drafts/:id)
    draft = plan_routes._load_draft(draft_id)
    assert draft is not None
    assert draft.status == "finalized", f"Expected status='finalized', got {draft.status!r}"

    # Step 7: Daemon must have enqueued the mission
    s = daemon_inst.status()
    assert mission_id in s["queue"], \
        f"Expected {mission_id!r} in daemon queue: {s['queue']}"

    # Step 8: GET /api/daemon/status shows the mission
    code, status_body = daemon_routes.get(None, ["", "api", "daemon"], {})
    assert code == 200
    assert mission_id in status_body["queue"], \
        f"Expected {mission_id!r} in daemon status queue: {status_body['queue']}"


def test_e2e_daemon_crash_recovery(tmp_path):
    """Daemon restart re-enqueues missions that were 'running' at time of crash.

    Simulates crash by writing a JSONL where a mission was started but never completed,
    then verifying a new MissionDaemon restores it to the queue.
    """
    import json as _json

    # Write JSONL simulating: mission enqueued, then started, but daemon crashed (no completed)
    queue_file = tmp_path / "daemon_queue.jsonl"
    queue_file.write_text(
        _json.dumps({"action": "enqueue", "mission_id": "crashed-m-01"}) + "\n"
        + _json.dumps({"action": "running", "mission_id": "crashed-m-01"}) + "\n"
    )

    # New daemon with same state_dir — _compact_queue() replays JSONL on __init__
    d = MissionDaemon(state_dir=tmp_path, max_concurrent=1, poll_interval=0.05)
    s = d.status()

    assert len(s["queue"]) >= 1, \
        f"Expected at least 1 mission in queue after crash recovery: {s}"
    assert "crashed-m-01" in s["queue"], \
        f"Expected 'crashed-m-01' in restored queue: {s['queue']}"
    assert s["queue"]["crashed-m-01"].get("interrupted") is True, \
        "Interrupted mission must be flagged interrupted=True in queue state"
