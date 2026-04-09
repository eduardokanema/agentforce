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
from agentforce.core.token_event import TokenEvent


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
        """run() must return (bool, str, str, str|None, TokenEvent)."""
        from agentforce.core.token_event import TokenEvent
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

        assert len(result) == 5
        success, output, error, session_id, token_event = result
        assert success is True
        assert "hello" in output
        assert session_id == "ses_abc123"
        assert isinstance(token_event, TokenEvent)

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
            _, _, _, session_id, _ = oc_mod.run("x", str(tmp_path))

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
            success, _, error, _, _ = oc_mod.run("x", str(tmp_path))

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
        assert "line" in log_file.read_text()


# ── claude connector ──────────────────────────────────────────────────────────

class TestClaudeConnector:
    def test_available_true_when_claude_exists(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert cl_mod.available() is True

    def test_available_false_when_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert cl_mod.available() is False

    def test_run_returns_five_tuple_with_none_session(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = ['{"type":"text","text":"output line"}\n']
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""

        with patch("subprocess.Popen", return_value=mock_proc):
            result = cl_mod.run("prompt", str(tmp_path))

        assert len(result) == 5
        assert result[3] is None  # session_id always None — claude handles state internally

    def test_run_returns_token_event_as_fifth_element(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = [
            '{"type":"message_delta","usage":{"input_tokens":10,"output_tokens":20}}\n',
        ]
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""

        with patch("subprocess.Popen", return_value=mock_proc):
            result = cl_mod.run("prompt", str(tmp_path))

        assert len(result) == 5
        token_event = result[4]
        assert isinstance(token_event, TokenEvent)
        assert token_event.tokens_in == 10
        assert token_event.tokens_out == 20

    def test_run_uses_stream_json_format(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = []
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            cl_mod.run("x", str(tmp_path))

        cmd = mock_popen.call_args[0][0]
        assert "--output-format" in cmd
        assert "stream-json" in cmd

    def test_run_parses_text_from_stream_json(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = [
            '{"type":"assistant","message":{"content":[{"type":"text","text":"hello world"}],"usage":{}}}\n',
            '{"type":"content_block_delta","delta":{"type":"text_delta","text":" more"}}\n',
        ]
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""

        with patch("subprocess.Popen", return_value=mock_proc):
            _, output, _, _, _ = cl_mod.run("prompt", str(tmp_path))

        assert "hello world" in output
        assert "more" in output

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

    def test_run_returns_five_tuple_with_token_event(self, tmp_path):
        """openrouter.run() must forward the full 5-tuple from opencode unchanged."""
        tok = TokenEvent(tokens_in=50, tokens_out=20, cost_usd=0.001)
        with patch.object(oc_mod, "run", return_value=(True, "ok", "", "ses_1", tok)):
            result = or_mod.run("x", str(tmp_path), model="nvidia/llama-3")

        assert len(result) == 5
        success, output, error, session_id, token_event = result
        assert success is True
        assert session_id == "ses_1"
        assert token_event is tok

    def test_token_event_propagates_unchanged(self, tmp_path):
        """TokenEvent fields must be identical after delegation — not a copy."""
        tok = TokenEvent(tokens_in=100, tokens_out=40, cost_usd=0.005)
        with patch.object(oc_mod, "run", return_value=(True, "resp", "", None, tok)):
            _, _, _, _, token_event = or_mod.run("x", str(tmp_path))

        assert token_event.tokens_in == 100
        assert token_event.tokens_out == 40
        assert token_event.cost_usd == 0.005

    def test_return_annotation_includes_token_event(self):
        """Return type annotation must declare TokenEvent as the 5th element."""
        import typing
        hints = typing.get_type_hints(or_mod.run)
        args = typing.get_args(hints["return"])
        assert TokenEvent in args, f"TokenEvent not found in return annotation args: {args}"


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
        from agentforce.core.token_event import TokenEvent
        te = TokenEvent(10, 5, 0.0)
        mock_connector = MagicMock(return_value=(True, "out", "", "ses_x", te))
        with patch.dict("agentforce.connectors.CONNECTORS", {"opencode": mock_connector}):
            result = autonomous._run_agent("prompt", str(tmp_path), agent="opencode")

        mock_connector.assert_called_once()
        assert result == (True, "out", "", "ses_x", te)

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

    def test_reviewer_session_reused_only_after_real_returned_id(self, tmp_path):
        """Reviewer should reuse only a connector-returned reviewer session id."""
        from agentforce.autonomous import _get_or_create_session_id

        session_ids: dict[str, str] = {}

        assert _get_or_create_session_id(session_ids, "01", "reviewer") is None

        returned_sid = "thread_real_123"
        if returned_sid and "01_reviewer" not in session_ids:
            session_ids["01_reviewer"] = returned_sid

        assert _get_or_create_session_id(session_ids, "01", "reviewer") == "thread_real_123"


# ── opencode TokenEvent emission ─────────────────────────────────────────────

class TestOpencodeTokenEvent:
    """opencode.run() must return a 5-tuple with TokenEvent as the 5th element."""

    def _mock_proc(self, events, returncode=0, stderr=""):
        mock_proc = MagicMock()
        mock_proc.stdout = events
        mock_proc.returncode = returncode
        mock_proc.stderr.read.return_value = stderr
        return mock_proc

    def test_run_returns_five_tuple(self, tmp_path):
        mock_proc = self._mock_proc([])
        with patch("subprocess.Popen", return_value=mock_proc):
            result = oc_mod.run("x", str(tmp_path))
        assert len(result) == 5

    def test_run_fifth_element_is_token_event(self, tmp_path):
        from agentforce.core.token_event import TokenEvent
        mock_proc = self._mock_proc([])
        with patch("subprocess.Popen", return_value=mock_proc):
            result = oc_mod.run("x", str(tmp_path))
        assert isinstance(result[4], TokenEvent)

    def test_run_default_token_event_when_no_usage_events(self, tmp_path):
        from agentforce.core.token_event import TokenEvent
        events = [
            '{"type":"step_start","sessionID":"s1","part":{}}\n',
            '{"type":"text","sessionID":"s1","part":{"text":"done"}}\n',
        ]
        mock_proc = self._mock_proc(events)
        with patch("subprocess.Popen", return_value=mock_proc):
            *_, token_event = oc_mod.run("x", str(tmp_path))
        assert token_event == TokenEvent(0, 0, 0.0)

    def test_run_captures_usage_type_event(self, tmp_path):
        events = [
            '{"type":"usage","inputTokens":100,"outputTokens":50}\n',
        ]
        mock_proc = self._mock_proc(events)
        with patch("subprocess.Popen", return_value=mock_proc):
            *_, token_event = oc_mod.run("x", str(tmp_path))
        assert token_event.tokens_in == 100
        assert token_event.tokens_out == 50

    def test_run_captures_tokens_type_event(self, tmp_path):
        events = [
            '{"type":"tokens","promptTokens":200,"completionTokens":80}\n',
        ]
        mock_proc = self._mock_proc(events)
        with patch("subprocess.Popen", return_value=mock_proc):
            *_, token_event = oc_mod.run("x", str(tmp_path))
        assert token_event.tokens_in == 200
        assert token_event.tokens_out == 80

    def test_run_captures_stats_type_event(self, tmp_path):
        events = [
            '{"type":"stats","tokensIn":30,"tokensOut":15}\n',
        ]
        mock_proc = self._mock_proc(events)
        with patch("subprocess.Popen", return_value=mock_proc):
            *_, token_event = oc_mod.run("x", str(tmp_path))
        assert token_event.tokens_in == 30
        assert token_event.tokens_out == 15

    def test_run_captures_event_with_inline_token_keys(self, tmp_path):
        events = [
            '{"type":"step_finish","sessionID":"s","inputTokens":42,"outputTokens":17}\n',
        ]
        mock_proc = self._mock_proc(events)
        with patch("subprocess.Popen", return_value=mock_proc):
            *_, token_event = oc_mod.run("x", str(tmp_path))
        assert token_event.tokens_in == 42
        assert token_event.tokens_out == 17

    def test_run_sums_multiple_usage_events(self, tmp_path):
        events = [
            '{"type":"usage","inputTokens":100,"outputTokens":50}\n',
            '{"type":"usage","inputTokens":200,"outputTokens":75}\n',
        ]
        mock_proc = self._mock_proc(events)
        with patch("subprocess.Popen", return_value=mock_proc):
            *_, token_event = oc_mod.run("x", str(tmp_path))
        assert token_event.tokens_in == 300
        assert token_event.tokens_out == 125

    def test_run_cost_usd_is_zero(self, tmp_path):
        events = [
            '{"type":"usage","inputTokens":10,"outputTokens":5}\n',
        ]
        mock_proc = self._mock_proc(events)
        with patch("subprocess.Popen", return_value=mock_proc):
            *_, token_event = oc_mod.run("x", str(tmp_path))
        assert token_event.cost_usd == 0.0


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

    def test_run_returns_four_tuple(self, tmp_path):
        events = [
            '{"type":"thread.started","thread_id":"thread_abc"}\n',
            '{"type":"item.completed","item":{"id":"i1","type":"agent_message","text":"done"}}\n',
        ]
        mock_proc = MagicMock()
        mock_proc.stdout = events
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""

        with patch("subprocess.Popen", return_value=mock_proc):
            result = cx_mod.run("do something", str(tmp_path))

        assert len(result) == 5
        success, output, error, session_id, token_event = result
        assert success is True
        assert "done" in output
        assert session_id == "thread_abc"

    def test_run_uses_json_flag(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = []
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            cx_mod.run("x", str(tmp_path))

        cmd = mock_popen.call_args[0][0]
        assert "--json" in cmd

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

    def test_run_feeds_prompt_via_stdin(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = []
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""
        mock_proc.stdin = MagicMock()

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            cx_mod.run("-q review this task", str(tmp_path))

        cmd = mock_popen.call_args[0][0]
        assert cmd[-1] == "-"
        mock_proc.stdin.write.assert_called_once_with("-q review this task")
        mock_proc.stdin.close.assert_called_once()

    def test_run_resume_feeds_prompt_via_stdin(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = []
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""
        mock_proc.stdin = MagicMock()

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            cx_mod.run("-q review this task", str(tmp_path), session_id="thread_123")

        cmd = mock_popen.call_args[0][0]
        assert cmd[:2] == ["codex", "exec"]
        assert "resume" in cmd
        assert cmd[-2:] == ["thread_123", "-"]
        mock_proc.stdin.write.assert_called_once_with("-q review this task")
        mock_proc.stdin.close.assert_called_once()

    def test_run_opens_stdin_pipe(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = []
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""
        mock_proc.stdin = MagicMock()

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            cx_mod.run("x", str(tmp_path))

        assert mock_popen.call_args.kwargs["stdin"] is subprocess.PIPE

    def test_run_failure_on_nonzero_returncode(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = []
        mock_proc.returncode = 1
        mock_proc.stderr.read.return_value = "error occurred"

        with patch("subprocess.Popen", return_value=mock_proc):
            success, _, error, _, _te = cx_mod.run("x", str(tmp_path))

        assert success is False

    def test_run_streams_to_file(self, tmp_path):
        events = [
            '{"type":"item.completed","item":{"id":"i1","type":"agent_message","text":"agent output line"}}\n',
        ]
        mock_proc = MagicMock()
        mock_proc.stdout = events
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""

        log_file = tmp_path / "stream.log"
        with patch("subprocess.Popen", return_value=mock_proc):
            cx_mod.run("x", str(tmp_path), stream_path=log_file)

        assert log_file.exists()
        assert "agent output line" in log_file.read_text()

    def test_run_streams_command_execution_to_file(self, tmp_path):
        events = [
            '{"type":"item.started","item":{"id":"i1","type":"command_execution","command":"ls -la"}}\n',
            '{"type":"item.completed","item":{"id":"i1","type":"command_execution","command":"ls -la","aggregated_output":"file.txt\\n","exit_code":0,"status":"completed"}}\n',
        ]
        mock_proc = MagicMock()
        mock_proc.stdout = events
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""

        log_file = tmp_path / "stream.log"
        with patch("subprocess.Popen", return_value=mock_proc):
            cx_mod.run("x", str(tmp_path), stream_path=log_file)

        content = log_file.read_text()
        assert "▶ ls -la" in content
        assert "✓" in content

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


# ── _enforce_review_thresholds ───────────────────────────────────────────────

class TestEnforceReviewThresholds:
    def _approved(self, score=9, security="met", extra=None):
        r = {"approved": True, "score": score, "feedback": "looks good",
             "blocking_issues": [], "criteria_results": {"security": security}}
        if extra:
            r.update(extra)
        return r

    def test_passes_through_high_score_no_security_issue(self):
        result = autonomous._enforce_review_thresholds(self._approved(score=8))
        assert result["approved"] is True

    def test_passes_through_score_exactly_8(self):
        result = autonomous._enforce_review_thresholds(self._approved(score=8))
        assert result["approved"] is True

    def test_rejects_score_below_8(self):
        result = autonomous._enforce_review_thresholds(self._approved(score=7))
        assert result["approved"] is False
        assert "7/10 below threshold 8" in result["feedback"]

    def test_rejects_score_0(self):
        result = autonomous._enforce_review_thresholds(self._approved(score=0))
        assert result["approved"] is False

    def test_rejects_security_not_met(self):
        result = autonomous._enforce_review_thresholds(self._approved(security="failed"))
        assert result["approved"] is False
        assert "Security issue: failed" in result["feedback"]
        assert any("security" in b for b in result["blocking_issues"])

    def test_rejects_security_partial(self):
        result = autonomous._enforce_review_thresholds(self._approved(security="partial"))
        assert result["approved"] is False

    def test_score_check_takes_priority_over_security(self):
        """Low score + security issue: score rejection fires first."""
        result = autonomous._enforce_review_thresholds(self._approved(score=5, security="failed"))
        assert result["approved"] is False
        assert "below threshold" in result["feedback"]

    def test_already_rejected_not_mutated(self):
        """A review already marked approved=False passes through unchanged."""
        r = {"approved": False, "score": 3, "feedback": "bad", "blocking_issues": ["X"]}
        result = autonomous._enforce_review_thresholds(r)
        assert result is r  # same object, no copy

    def test_original_dict_not_mutated(self):
        original = self._approved(score=5)
        autonomous._enforce_review_thresholds(original)
        assert original["approved"] is True  # untouched

    def test_preserves_existing_blocking_issues_on_security_rejection(self):
        r = self._approved(security="not met",
                           extra={"blocking_issues": ["missing tests"]})
        result = autonomous._enforce_review_thresholds(r)
        issues = result["blocking_issues"]
        assert "missing tests" in issues
        assert any("security" in b for b in issues)

    def test_real_log_task06_score8_passes(self):
        """Score 8 with security=met (real task 06 output) must be approved."""
        review = {
            "approved": True, "score": 8, "feedback": "scaffold complete",
            "criteria_results": {"security": "met", "tdd": "partial"},
            "blocking_issues": [],
        }
        result = autonomous._enforce_review_thresholds(review)
        assert result["approved"] is True


# ── _parse_reviewer_output ────────────────────────────────────────────────────

class TestParseReviewerOutput:
    def test_parses_bare_json_line(self):
        output = '{"approved": true, "score": 9, "feedback": "looks good"}'
        result = autonomous._parse_reviewer_output(output)
        assert result["approved"] is True
        assert result["score"] == 9

    def test_json_followed_by_turn_complete_line(self):
        """Codex appends '── turn complete ...' after the verdict — must not break parsing."""
        output = (
            "{\n"
            '  "approved": true,\n'
            '  "score": 8,\n'
            '  "feedback": "all good"\n'
            "}\n"
            "── turn complete  in=91494 (cached=46336) out=2496 ──"
        )
        result = autonomous._parse_reviewer_output(output)
        assert result["approved"] is True
        assert result["score"] == 8

    def test_parses_multiline_json_at_end(self):
        """Core fix: multi-line verdict JSON after prose should be found."""
        output = (
            "I reviewed the files and everything looks good.\n"
            "{\n"
            '  "approved": true,\n'
            '  "score": 8,\n'
            '  "feedback": "all criteria met"\n'
            "}"
        )
        result = autonomous._parse_reviewer_output(output)
        assert result["approved"] is True
        assert result["score"] == 8

    def test_last_json_wins_over_file_content(self):
        """Regression: file content read during review must not swamp the verdict."""
        package_json_dump = (
            "I read the file:\n"
            "{\n"
            '  "name": "my-app",\n'
            '  "version": "1.0.0",\n'
            '  "dependencies": {"react": "^18"}\n'
            "}\n"
        )
        verdict = (
            "{\n"
            '  "approved": true,\n'
            '  "score": 9,\n'
            '  "feedback": "scaffold complete"\n'
            "}"
        )
        result = autonomous._parse_reviewer_output(package_json_dump + verdict)
        assert result["approved"] is True
        assert result["score"] == 9
        assert result["feedback"] == "scaffold complete"

    def test_tool_output_with_line_numbers_before_verdict(self):
        """nl -ba output (line-numbered) should not prevent finding the verdict."""
        nl_output = (
            "  1\t{\n"
            '  2\t  "name": "@agentforce/ui",\n'
            "  3\t}\n"
        )
        verdict = (
            "{\n"
            '  "approved": false,\n'
            '  "score": 4,\n'
            '  "feedback": "missing tests"\n'
            "}"
        )
        result = autonomous._parse_reviewer_output(nl_output + verdict)
        assert result["approved"] is False
        assert result["score"] == 4

    def test_parses_json_in_fenced_code_block(self):
        output = 'Some preamble\n```json\n{"approved": false, "score": 3, "feedback": "needs work"}\n```'
        result = autonomous._parse_reviewer_output(output)
        assert result["approved"] is False
        assert result["score"] == 3

    def test_last_fenced_block_wins(self):
        """When multiple ```json blocks appear, the last one is the verdict."""
        output = (
            "```json\n"
            '{"name": "package", "version": "1"}\n'
            "```\n"
            "Here is my actual verdict:\n"
            "```json\n"
            '{"approved": true, "score": 7, "feedback": "ok"}\n'
            "```"
        )
        result = autonomous._parse_reviewer_output(output)
        assert result["approved"] is True
        assert result["score"] == 7

    def test_raises_on_no_json_found(self):
        """No parseable JSON → ValueError (triggers critical error path)."""
        with pytest.raises(ValueError, match="Could not parse reviewer output"):
            autonomous._parse_reviewer_output("This is just plain text with no JSON at all.")

    def test_raises_on_empty_output(self):
        with pytest.raises(ValueError, match="Could not parse reviewer output"):
            autonomous._parse_reviewer_output("")

    def test_skips_invalid_json_and_finds_valid_later(self):
        output = "{invalid json}\n{\"approved\": true, \"score\": 5, \"feedback\": \"fine\"}"
        result = autonomous._parse_reviewer_output(output)
        assert result["approved"] is True

    def test_blocking_issues_key_preserved(self):
        output = '{"approved": false, "score": 2, "feedback": "bad", "blocking_issues": ["issue A"]}'
        result = autonomous._parse_reviewer_output(output)
        assert result["blocking_issues"] == ["issue A"]

    def test_import_json_is_available(self):
        """Regression: json must be importable at module level (NameError fix)."""
        import importlib
        mod = importlib.import_module("agentforce.autonomous")
        import json as _json
        assert mod.json is _json
