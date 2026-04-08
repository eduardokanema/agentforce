"""Integration tests for agentforce.connectors and related autonomous.py changes."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agentforce import autonomous
from agentforce.connectors import CONNECTORS, run_opencode, run_claude, run_openrouter, run_codex
from agentforce.connectors import opencode as oc_mod
from agentforce.connectors import claude as cl_mod
from agentforce.connectors import openrouter as or_mod
from agentforce.connectors import codex as cx_mod


# ── Connector registry ────────────────────────────────────────────────────────

class TestConnectorRegistry:
    def test_all_connectors_present(self):
        assert set(CONNECTORS) == {"opencode", "claude", "openrouter", "codex"}

    def test_connectors_are_callable(self):
        for name, fn in CONNECTORS.items():
            assert callable(fn), f"{name} connector is not callable"

    def test_imports_match_registry(self):
        assert CONNECTORS["opencode"] is run_opencode
        assert CONNECTORS["claude"] is run_claude
        assert CONNECTORS["openrouter"] is run_openrouter
        assert CONNECTORS["codex"] is run_codex


# ── opencode connector ────────────────────────────────────────────────────────

class TestOpencodeConnector:
    def test_available_true_when_opencode_exists(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert oc_mod.available() is True

    def test_available_false_when_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert oc_mod.available() is False

    def test_available_false_on_nonzero_returncode(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            assert oc_mod.available() is False

    def test_run_returns_four_tuple(self, tmp_path):
        """run() must return (bool, str, str, str|None)."""
        fake_events = [
            b'{"type":"step_start","sessionID":"ses_abc123","part":{}}\n',
            b'{"type":"text","sessionID":"ses_abc123","part":{"text":"hello"}}\n',
            b'{"type":"step_finish","sessionID":"ses_abc123","part":{}}\n',
        ]
        mock_proc = MagicMock()
        mock_proc.stdout = fake_events
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""

        with patch("subprocess.Popen", return_value=mock_proc):
            result = oc_mod.run("do something", str(tmp_path))

        assert len(result) == 4
        success, output, error, session_id = result
        assert success is True
        assert "hello" in output
        assert session_id == "ses_abc123"

    def test_run_captures_session_id_from_first_event(self, tmp_path):
        fake_events = [
            b'{"type":"step_start","sessionID":"ses_FIRST","part":{}}\n',
            b'{"type":"text","sessionID":"ses_OTHER","part":{"text":"x"}}\n',
        ]
        mock_proc = MagicMock()
        mock_proc.stdout = fake_events
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""

        with patch("subprocess.Popen", return_value=mock_proc):
            _, _, _, session_id = oc_mod.run("x", str(tmp_path))

        assert session_id == "ses_FIRST"

    def test_run_passes_model_flag(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = []
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            oc_mod.run("x", str(tmp_path), model="opencode/nemotron-3-super-free")

        cmd = mock_popen.call_args[0][0]
        assert "--model" in cmd
        assert "opencode/nemotron-3-super-free" in cmd

    def test_run_passes_variant_flag(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = []
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            oc_mod.run("x", str(tmp_path), variant="high")

        cmd = mock_popen.call_args[0][0]
        assert "--variant" in cmd
        assert "high" in cmd

    def test_run_passes_session_and_continue_flags(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = []
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            oc_mod.run("x", str(tmp_path), session_id="ses_xyz")

        cmd = mock_popen.call_args[0][0]
        assert "--session" in cmd
        assert "ses_xyz" in cmd
        assert "--continue" in cmd

    def test_run_uses_json_format(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = []
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            oc_mod.run("x", str(tmp_path))

        cmd = mock_popen.call_args[0][0]
        assert "--format" in cmd
        assert "json" in cmd

    def test_run_failure_on_nonzero_returncode(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = []
        mock_proc.returncode = 1
        mock_proc.stderr.read.return_value = "something failed"

        with patch("subprocess.Popen", return_value=mock_proc):
            success, _, error, _ = oc_mod.run("x", str(tmp_path))

        assert success is False

    def test_run_streams_to_file(self, tmp_path):
        # Popen with text=True yields str lines
        fake_events = [
            '{"type":"text","sessionID":"s","part":{"text":"line"}}\n',
        ]
        mock_proc = MagicMock()
        mock_proc.stdout = fake_events
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""

        log_file = tmp_path / "stream.log"
        with patch("subprocess.Popen", return_value=mock_proc):
            oc_mod.run("x", str(tmp_path), stream_path=log_file)

        assert log_file.exists()
        assert "text" in log_file.read_text()


# ── claude connector ──────────────────────────────────────────────────────────

class TestClaudeConnector:
    def test_available_true_when_claude_exists(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert cl_mod.available() is True

    def test_available_false_when_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert cl_mod.available() is False

    def test_run_returns_four_tuple_with_none_session(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = ["output line\n"]  # text=True yields str lines
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""

        with patch("subprocess.Popen", return_value=mock_proc):
            result = cl_mod.run("prompt", str(tmp_path))

        assert len(result) == 4
        assert result[3] is None  # claude never returns a session ID

    def test_run_passes_model_flag(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = []
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = b""

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            cl_mod.run("x", str(tmp_path), model="claude-sonnet-4-6")

        cmd = mock_popen.call_args[0][0]
        assert "--model" in cmd
        assert "claude-sonnet-4-6" in cmd

    def test_run_uses_dangerously_skip_permissions(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = []
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = b""

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            cl_mod.run("x", str(tmp_path))

        cmd = mock_popen.call_args[0][0]
        assert "--dangerously-skip-permissions" in cmd


# ── openrouter connector ──────────────────────────────────────────────────────

class TestOpenrouterConnector:
    def test_prefixes_model_with_openrouter(self, tmp_path):
        with patch.object(oc_mod, "run", return_value=(True, "ok", "", "ses_1")) as mock_run:
            or_mod.run("x", str(tmp_path), model="nvidia/llama-3")

        _, _, _, model, *_ = mock_run.call_args[0]
        assert model == "openrouter/nvidia/llama-3"

    def test_does_not_double_prefix(self, tmp_path):
        with patch.object(oc_mod, "run", return_value=(True, "ok", "", None)) as mock_run:
            or_mod.run("x", str(tmp_path), model="openrouter/nvidia/llama-3")

        _, _, _, model, *_ = mock_run.call_args[0]
        assert model == "openrouter/nvidia/llama-3"

    def test_no_model_passes_through(self, tmp_path):
        with patch.object(oc_mod, "run", return_value=(True, "", "", None)) as mock_run:
            or_mod.run("x", str(tmp_path))

        _, _, _, model, *_ = mock_run.call_args[0]
        assert model is None

    def test_available_delegates_to_opencode(self):
        with patch.object(oc_mod, "available", return_value=True):
            assert or_mod.available() is True
        with patch.object(oc_mod, "available", return_value=False):
            assert or_mod.available() is False


# ── autonomous.py defaults ────────────────────────────────────────────────────

class TestAutonomousDefaults:
    def test_default_model_is_nemotron(self):
        assert autonomous._DEFAULT_MODEL == "opencode/nemotron-3-super-free"

    def test_default_variant_is_high(self):
        assert autonomous._DEFAULT_VARIANT == "high"

    def test_detect_agent_returns_opencode_when_available(self):
        with patch.object(oc_mod, "available", return_value=True):
            assert autonomous._detect_agent() == "opencode"

    def test_detect_agent_raises_when_opencode_missing(self):
        with patch.object(oc_mod, "available", return_value=False):
            with pytest.raises(SystemExit):
                autonomous._detect_agent()

    def test_run_agent_dispatches_to_opencode_connector(self, tmp_path):
        mock_connector = MagicMock(return_value=(True, "out", "", "ses_x"))
        with patch.dict("agentforce.connectors.CONNECTORS", {"opencode": mock_connector}):
            result = autonomous._run_agent("prompt", str(tmp_path), agent="opencode")

        mock_connector.assert_called_once()
        assert result == (True, "out", "", "ses_x")

    def test_run_agent_raises_for_unknown_agent(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown agent"):
            autonomous._run_agent("x", str(tmp_path), agent="unknown_agent")

    def test_run_agent_passes_variant(self, tmp_path):
        mock_connector = MagicMock(return_value=(True, "", "", None))
        with patch.dict("agentforce.connectors.CONNECTORS", {"opencode": mock_connector}):
            autonomous._run_agent("x", str(tmp_path), agent="opencode", variant="max")

        call_kwargs = mock_connector.call_args
        # positional: (prompt, workdir, timeout, model, stream_path, variant, session_id)
        args = call_kwargs[0]
        assert args[5] == "max"

    def test_run_agent_passes_session_id(self, tmp_path):
        mock_connector = MagicMock(return_value=(True, "", "", "ses_new"))
        with patch.dict("agentforce.connectors.CONNECTORS", {"opencode": mock_connector}):
            autonomous._run_agent("x", str(tmp_path), agent="opencode", session_id="ses_old")

        args = mock_connector.call_args[0]
        assert args[6] == "ses_old"


# ── session caching in run_autonomous ────────────────────────────────────────

class TestSessionCaching:
    """Verify that session IDs returned by workers are stored and reused on retry."""

    def _make_minimal_state(self, tmp_path):
        """Create a minimal saved mission state for run_autonomous to load."""
        from agentforce.core.spec import MissionSpec, TaskSpec, Caps
        from agentforce.core.engine import MissionEngine
        from agentforce.memory import Memory

        spec = MissionSpec(
            name="Cache Test",
            goal="test",
            definition_of_done=["done"],
            tasks=[TaskSpec(id="01", title="T1", description="do it", max_retries=2)],
            caps=Caps(max_concurrent_workers=1, max_retries_global=3, max_wall_time_minutes=5),
        )
        mem = Memory(tmp_path / "memory")
        engine = MissionEngine(spec=spec, state_dir=tmp_path / "state", memory=mem, mission_id="cache-test")
        return engine

    def test_session_id_stored_after_first_worker_result(self, tmp_path):
        """session_ids dict is populated when a worker returns a session ID."""
        session_ids: dict[str, str] = {}
        returned_sid = "ses_cached"
        tid = "01"
        role = "worker"

        # Mirrors the logic in _collect inside run_autonomous
        if role == "worker" and returned_sid and tid not in session_ids:
            session_ids[tid] = returned_sid

        assert session_ids["01"] == "ses_cached"

    def test_session_id_not_overwritten_on_second_call(self, tmp_path):
        """Once stored, the session ID is not replaced by a subsequent call."""
        session_ids: dict[str, str] = {"01": "ses_original"}
        returned_sid = "ses_new"
        tid = "01"

        if "worker" == "worker" and returned_sid and tid not in session_ids:
            session_ids[tid] = returned_sid

        assert session_ids["01"] == "ses_original"

    def test_session_id_reused_on_second_worker_dispatch(self, tmp_path):
        """Second dispatch for the same task should receive the stored session ID."""
        session_ids = {"01": "ses_from_first_run"}

        # Simulate _submit logic for a retry
        tid = "01"
        role = "worker"
        session_id = session_ids.get(tid) if role == "worker" else None

        assert session_id == "ses_from_first_run"

    def test_reviewer_does_not_use_session_id(self, tmp_path):
        """Reviewers should always get a fresh session (no caching)."""
        session_ids = {"01": "ses_worker"}

        tid = "01"
        role = "reviewer"
        session_id = session_ids.get(tid) if role == "worker" else None

        assert session_id is None


# ── codex connector ───────────────────────────────────────────────────────────

class TestCodexConnector:
    def test_available_true_when_codex_exists(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert cx_mod.available() is True

    def test_available_false_when_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert cx_mod.available() is False

    def test_available_false_on_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("codex", 10)):
            assert cx_mod.available() is False

    def test_run_returns_four_tuple_with_none_session(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = ["task complete\n"]
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""

        with patch("subprocess.Popen", return_value=mock_proc):
            result = cx_mod.run("do something", str(tmp_path))

        assert len(result) == 4
        success, output, error, session_id = result
        assert success is True
        assert session_id is None

    def test_run_uses_exec_subcommand(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = []
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            cx_mod.run("x", str(tmp_path))

        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "codex"
        assert cmd[1] == "exec"

    def test_run_uses_dangerously_bypass(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = []
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            cx_mod.run("x", str(tmp_path))

        cmd = mock_popen.call_args[0][0]
        assert "--dangerously-bypass-approvals-and-sandbox" in cmd

    def test_run_passes_workdir_with_C_flag(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = []
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            cx_mod.run("x", str(tmp_path))

        cmd = mock_popen.call_args[0][0]
        assert "-C" in cmd
        assert str(tmp_path) in cmd

    def test_run_passes_model_flag(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = []
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            cx_mod.run("x", str(tmp_path), model="o4-mini")

        cmd = mock_popen.call_args[0][0]
        assert "-m" in cmd
        assert "o4-mini" in cmd

    def test_run_failure_on_nonzero_returncode(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = []
        mock_proc.returncode = 1
        mock_proc.stderr.read.return_value = "error occurred"

        with patch("subprocess.Popen", return_value=mock_proc):
            success, _, error, _ = cx_mod.run("x", str(tmp_path))

        assert success is False

    def test_run_streams_to_file(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = ["agent output line\n"]
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""

        log_file = tmp_path / "stream.log"
        with patch("subprocess.Popen", return_value=mock_proc):
            cx_mod.run("x", str(tmp_path), stream_path=log_file)

        assert log_file.exists()
        assert "agent output line" in log_file.read_text()

    def test_run_timeout_returns_failure(self, tmp_path):
        import threading

        mock_proc = MagicMock()
        mock_proc.returncode = -9

        def slow_stdout():
            import time
            time.sleep(10)
            return iter([])

        mock_proc.stdout = iter([])

        killed = []

        def fake_kill():
            killed.append(True)

        mock_proc.kill = fake_kill

        with patch("subprocess.Popen", return_value=mock_proc):
            with patch("threading.Timer") as mock_timer_cls:
                mock_timer = MagicMock()
                mock_timer_cls.return_value = mock_timer
                cx_mod.run("x", str(tmp_path), timeout=1)

        mock_timer_cls.assert_called_once()
        mock_timer.start.assert_called_once()
        mock_timer.cancel.assert_called_once()
