"""MissionDaemon — supervisor that queues and runs autonomous missions.

Manages when and which missions run; does NOT alter how they run.
run_autonomous() is called as-is, wrapped only in exception handling.
"""
from __future__ import annotations

import fcntl
import json
import logging
import logging.handlers
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from agentforce.autonomous import pause_mission, run_autonomous

_DEFAULT_STATE_DIR = Path.home() / ".agentforce"
_QUEUE_FILE = "daemon_queue.jsonl"
_LOCK_FILE = "daemon.lock"

# Module-level guard: prevents two MissionDaemon instances in the same process
# from both believing they hold the file lock (fcntl is per-process, not per-fd).
_process_lock_held: bool = False


class DaemonAlreadyRunning(Exception):
    """Raised when a second daemon instance attempts to acquire the daemon lock."""


class DaemonLock:
    """Exclusive daemon lock backed by fcntl.flock() + an in-process guard.

    Held for the lifetime of a running daemon process. The OS releases the
    fcntl lock automatically on process death, so no explicit cleanup is
    needed after SIGKILL.
    """

    def __init__(self, lock_path: Path) -> None:
        self._path = lock_path
        self._handle = None

    def __enter__(self) -> "DaemonLock":
        global _process_lock_held  # noqa: PLW0603
        if _process_lock_held:
            raise DaemonAlreadyRunning(
                "Another MissionDaemon instance in this process already holds the lock"
            )
        self._handle = self._path.open("w")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            self._handle.close()
            self._handle = None
            raise DaemonAlreadyRunning(
                f"Another daemon process already holds {self._path}"
            ) from exc
        self._handle.write(str(os.getpid()))
        self._handle.flush()
        _process_lock_held = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        global _process_lock_held  # noqa: PLW0603
        if self._handle is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None
        _process_lock_held = False


@dataclass
class DaemonCallbacks:
    """Optional lifecycle callbacks — wired by the server, not imported by this module."""

    on_enqueue: Optional[Callable] = field(default=None)
    on_start: Optional[Callable] = field(default=None)
    on_complete: Optional[Callable] = field(default=None)
    on_fail: Optional[Callable] = field(default=None)
    on_status_changed: Optional[Callable] = field(default=None)


class MissionDaemon:
    """Supervisor that maintains an ordered execution queue of missions.

    Args:
        state_dir: Directory for daemon_queue.jsonl (default ~/.agentforce).
        max_concurrent: Max missions running simultaneously (default 2).
        max_drain_seconds: Seconds to wait for in-flight missions before
            pausing them on stop() (default 30).
        poll_interval: Supervisor loop tick interval in seconds (default 2).
    """

    def __init__(
        self,
        state_dir: Optional[Path] = None,
        max_concurrent: int = 2,
        max_drain_seconds: int = 30,
        poll_interval: float = 2.0,
        notify_queue: Optional["_queue.Queue[str]"] = None,
        callbacks: Optional[DaemonCallbacks] = None,
    ) -> None:
        import queue as _q
        self._state_dir = Path(state_dir) if state_dir else _DEFAULT_STATE_DIR
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._queue_path = self._state_dir / _QUEUE_FILE

        self.max_concurrent = max_concurrent
        self.max_drain_seconds = max_drain_seconds
        self._poll_interval = poll_interval
        self._notify_queue: Optional[_q.Queue] = notify_queue
        self._callbacks: DaemonCallbacks = callbacks or DaemonCallbacks()

        self._lock = threading.Lock()
        self._journal_lock = threading.Lock()      # protects JSONL file writes
        self._queue: list[str] = []               # ordered, waiting missions
        self._mission_states: dict[str, dict] = {}  # all known mission states
        self._active_threads: dict[str, threading.Thread] = {}

        self._stop_event = threading.Event()
        self._stopping = False
        self._supervisor_thread: Optional[threading.Thread] = None
        self._daemon_lock: Optional[DaemonLock] = None

        # Restore state from previous run
        self._compact_queue()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, mission_id: str) -> None:
        """Add a mission to the execution queue."""
        with self._lock:
            if self._stopping:
                raise RuntimeError("Daemon is stopping; not accepting new missions")
            existing = self._mission_states.get(mission_id, {}).get("state")
            if existing in (None, "completed", "failed", "dequeued"):
                self._queue.append(mission_id)
                self._mission_states[mission_id] = {
                    "state": "queued",
                    "enqueued_at": self._now(),
                }
        self._append_journal({"action": "enqueue", "mission_id": mission_id})
        if self._notify_queue is not None:
            self._notify_queue.put_nowait(mission_id)
        if self._callbacks.on_enqueue is not None:
            self._callbacks.on_enqueue({"type": "daemon:enqueued", "mission_id": mission_id})

    def dequeue(self, mission_id: str) -> bool:
        """Remove a queued (not yet running) mission. Returns True if removed."""
        with self._lock:
            if mission_id in self._queue:
                self._queue.remove(mission_id)
                self._mission_states[mission_id] = {"state": "dequeued"}
        self._append_journal({"action": "dequeue", "mission_id": mission_id})
        return True

    def start(self) -> None:
        """Start the background supervisor loop.

        Raises DaemonAlreadyRunning if another daemon holds the exclusive lock.
        """
        if self._supervisor_thread and self._supervisor_thread.is_alive():
            return
        lock = DaemonLock(self._state_dir / _LOCK_FILE)
        lock.__enter__()  # raises DaemonAlreadyRunning if lock is held
        self._daemon_lock = lock
        self._stop_event.clear()
        self._stopping = False
        self._supervisor_thread = threading.Thread(
            target=self._supervisor_loop,
            name="daemon-supervisor",
            daemon=True,
        )
        self._supervisor_thread.start()
        if self._callbacks.on_status_changed is not None:
            self._callbacks.on_status_changed({"type": "daemon:status_changed", "running": True})

    def stop(self) -> None:
        """Gracefully stop: drain in-flight missions, then pause stragglers."""
        with self._lock:
            self._stopping = True

        # Wait up to max_drain_seconds for running missions to finish naturally
        deadline = time.monotonic() + self.max_drain_seconds
        while time.monotonic() < deadline:
            with self._lock:
                alive = [t for t in self._active_threads.values() if t.is_alive()]
            if not alive:
                break
            time.sleep(0.1)

        # Pause any missions still running after drain timeout
        with self._lock:
            for mid, thread in list(self._active_threads.items()):
                if thread.is_alive():
                    pause_mission(mid)
                    self._mission_states[mid]["state"] = "paused"
                    self._append_journal({"action": "paused", "mission_id": mid})

        self._stop_event.set()
        if self._supervisor_thread:
            self._supervisor_thread.join(timeout=5.0)
        if self._daemon_lock is not None:
            self._daemon_lock.__exit__(None, None, None)
            self._daemon_lock = None
        if self._callbacks.on_status_changed is not None:
            self._callbacks.on_status_changed({"type": "daemon:status_changed", "running": False})

    def status(self) -> dict:
        """Return current daemon status dict with 'running', 'queue', 'active'."""
        with self._lock:
            running = bool(
                self._supervisor_thread and self._supervisor_thread.is_alive()
            )
            queue = {
                mid: dict(state)
                for mid, state in self._mission_states.items()
                if state.get("state") == "queued"
            }
            active = {
                mid: dict(state)
                for mid, state in self._mission_states.items()
                if state.get("state") == "running"
            }
        return {"running": running, "queue": queue, "active": active}

    # ------------------------------------------------------------------
    # Internal — supervisor loop
    # ------------------------------------------------------------------

    def _supervisor_loop(self) -> None:
        import queue as _q
        while not self._stop_event.is_set():
            self._tick()
            self._append_journal({"action": "heartbeat"})
            if self._notify_queue is not None:
                try:
                    self._notify_queue.get(timeout=self._poll_interval)
                except _q.Empty:
                    pass
            else:
                self._stop_event.wait(timeout=self._poll_interval)

    def _tick(self) -> None:
        """Reap finished threads; dispatch queued missions up to max_concurrent."""
        pending_start_events: list[dict] = []
        with self._lock:
            # Reap finished mission threads
            for mid in list(self._active_threads.keys()):
                if not self._active_threads[mid].is_alive():
                    del self._active_threads[mid]

            if self._stopping:
                return

            # Dispatch up to available slots
            slots = self.max_concurrent - len(self._active_threads)
            to_dispatch: list[str] = []
            for mid in self._queue:
                if slots <= 0:
                    break
                if self._mission_states.get(mid, {}).get("state") == "queued":
                    to_dispatch.append(mid)
                    slots -= 1

            for mid in to_dispatch:
                self._queue.remove(mid)
                self._mission_states[mid]["state"] = "running"
                self._mission_states[mid]["started_at"] = self._now()
                t = threading.Thread(
                    target=self._run_mission,
                    args=(mid,),
                    name=f"mission-{mid}",
                    daemon=True,
                )
                self._active_threads[mid] = t
                t.start()
                self._append_journal({"action": "running", "mission_id": mid})
                pending_start_events.append({"type": "daemon:started", "mission_id": mid})

        # Fire callbacks outside the lock to avoid blocking I/O under contention
        cb = self._callbacks
        if cb.on_start is not None:
            for event in pending_start_events:
                cb.on_start(event)

    def _run_mission(self, mission_id: str) -> None:
        """Execute one mission, catching SystemExit so the daemon survives."""
        success = True
        error_str: Optional[str] = None
        try:
            run_autonomous(mission_id)
        except SystemExit:
            pass
        except Exception as exc:
            success = False
            error_str = str(exc)

        final = "completed" if success else "failed"
        with self._lock:
            if self._mission_states.get(mission_id, {}).get("state") == "running":
                self._mission_states[mission_id]["state"] = final
        self._append_journal({"action": final, "mission_id": mission_id})
        cb = self._callbacks
        if success and cb.on_complete is not None:
            cb.on_complete({"type": "daemon:completed", "mission_id": mission_id})
        elif not success and cb.on_fail is not None:
            cb.on_fail({"type": "daemon:failed", "mission_id": mission_id, "error": error_str or ""})

    # ------------------------------------------------------------------
    # Internal — JSONL persistence
    # ------------------------------------------------------------------

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _append_journal(self, record: dict) -> None:
        record.setdefault("ts", self._now())
        with self._journal_lock:
            try:
                with open(self._queue_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record) + "\n")
            except OSError:
                pass  # best-effort; don't crash the daemon over log writes

    def _compact_queue(self) -> None:
        """Replay JSONL log to reconstruct queue state from a previous run."""
        if not self._queue_path.exists():
            return
        try:
            lines = self._queue_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return

        order: list[str] = []
        states: dict[str, str] = {}

        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            action = rec.get("action")
            mid = rec.get("mission_id")

            if action == "enqueue" and mid:
                if mid not in states:
                    order.append(mid)
                states[mid] = "queued"
            elif action == "dequeue" and mid:
                states[mid] = "dequeued"
                if mid in order:
                    order.remove(mid)
            elif action == "running" and mid:
                # Was in-flight when daemon last stopped — treat as interrupted
                states[mid] = "running"
            elif action in ("completed", "failed", "paused") and mid:
                states[mid] = action
                if mid in order:
                    order.remove(mid)
            # heartbeat — skip

        with self._lock:
            for mid in order:
                s = states.get(mid, "queued")
                if s == "queued":
                    self._queue.append(mid)
                    self._mission_states[mid] = {"state": "queued"}
                elif s == "running":
                    # Interrupted: re-enqueue; run_autonomous resets IN_PROGRESS tasks
                    self._queue.append(mid)
                    self._mission_states[mid] = {
                        "state": "queued",
                        "interrupted": True,
                    }


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

_PID_FILE = "daemon.pid"
_LOG_FILE = "daemon.log"
_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_LOG_BACKUP_COUNT = 3


def _get_state_dir() -> Path:
    """Return state dir from AGENTFORCE_STATE_DIR env var or the default."""
    env = os.environ.get("AGENTFORCE_STATE_DIR")
    return Path(env) if env else _DEFAULT_STATE_DIR


def _setup_logging(state_dir: Path) -> logging.handlers.RotatingFileHandler:
    """Configure rotating file logging for the daemon process. Returns the handler."""
    state_dir.mkdir(parents=True, exist_ok=True)
    log_path = state_dir / _LOG_FILE
    handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=_LOG_MAX_BYTES,
        backupCount=_LOG_BACKUP_COUNT,
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.root.setLevel(logging.INFO)
    logging.root.addHandler(handler)
    return handler


def _cmd_run(state_dir: Path) -> None:
    """Internal entry point executed inside the detached child process."""
    _setup_logging(state_dir)
    pid_file = state_dir / _PID_FILE

    try:
        daemon = MissionDaemon(state_dir=state_dir)
        daemon.start()
    except DaemonAlreadyRunning as exc:
        print(f"error: already running — {exc}", file=sys.stderr)
        sys.exit(1)

    pid_file.write_text(str(os.getpid()))

    shutdown = threading.Event()

    def _handle_sigterm(signum, frame) -> None:
        shutdown.set()

    signal.signal(signal.SIGTERM, _handle_sigterm)

    try:
        shutdown.wait()
    finally:
        daemon.stop()
        try:
            pid_file.unlink()
        except FileNotFoundError:
            pass


def _cmd_start(state_dir: Path) -> None:
    """Spawn a detached child daemon and wait for its PID file to appear."""
    state_dir.mkdir(parents=True, exist_ok=True)

    child = subprocess.Popen(
        [sys.executable, "-m", "agentforce.daemon", "_run"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env={**os.environ, "AGENTFORCE_STATE_DIR": str(state_dir)},
        start_new_session=True,
    )

    pid_file = state_dir / _PID_FILE
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if pid_file.exists():
            break
        if child.poll() is not None:
            stderr = child.stderr.read().decode(errors="replace").strip()
            print(
                f"error: {stderr or 'daemon process exited unexpectedly'}",
                file=sys.stderr,
            )
            sys.exit(1)
        time.sleep(0.05)
    else:
        child.kill()
        stderr_text = child.stderr.read().decode(errors="replace").strip() if child.stderr else ""
        print(f"error: daemon did not write pid file in time. {stderr_text}", file=sys.stderr)
        sys.exit(1)

    child.stderr.close()
    pid = int(pid_file.read_text().strip())
    print(f"Daemon started (pid {pid})")


def _cmd_stop(state_dir: Path) -> None:
    """Send SIGTERM to the daemon, wait up to 10s, then SIGKILL if needed."""
    pid_file = state_dir / _PID_FILE
    if not pid_file.exists():
        print("error: daemon is not running (no pid file)", file=sys.stderr)
        sys.exit(1)

    pid = int(pid_file.read_text().strip())

    # Verify it's an agentforce process (best-effort on macOS)
    try:
        check = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
        )
        cmdline = check.stdout.strip()
        if cmdline and "agentforce" not in cmdline and "daemon" not in cmdline:
            print(f"warning: pid {pid} does not look like an agentforce process: {cmdline!r}")
    except Exception:
        pass

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        try:
            pid_file.unlink()
        except FileNotFoundError:
            pass
        print("Daemon was not running.")
        return

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, OSError):
            break
        time.sleep(0.1)
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass

    try:
        pid_file.unlink()
    except FileNotFoundError:
        pass
    print(f"Daemon stopped (pid {pid})")


def _cmd_status(state_dir: Path) -> None:
    """Print daemon running state and queue summary."""
    pid_file = state_dir / _PID_FILE
    if not pid_file.exists():
        print("stopped")
        return

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
    except (ValueError, ProcessLookupError, OSError):
        print("stopped")
        return

    print(f"running (pid {pid})")

    queue_file = state_dir / _QUEUE_FILE
    if queue_file.exists():
        print(f"Queue: {queue_file}")


# ---------------------------------------------------------------------------
# __main__ entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Usage: python3 -m agentforce.daemon [start|stop|status]", file=sys.stderr)
        sys.exit(1)

    _state_dir = _get_state_dir()
    _cmd = args[0]

    if _cmd == "start":
        _cmd_start(_state_dir)
    elif _cmd == "stop":
        _cmd_stop(_state_dir)
    elif _cmd == "status":
        _cmd_status(_state_dir)
    elif _cmd == "_run":
        _cmd_run(_state_dir)
    else:
        print(f"error: unknown command {_cmd!r}", file=sys.stderr)
        sys.exit(1)
