"""Tests for TokenEvent dataclass and Codex connector TokenEvent emission."""
from __future__ import annotations

import dataclasses
import json
from unittest.mock import MagicMock, patch

import pytest


# ── TokenEvent dataclass ──────────────────────────────────────────────────────

class TestTokenEventImport:
    def test_import_cleanly(self):
        from agentforce.core.token_event import TokenEvent  # noqa: F401

    def test_is_dataclass(self):
        from agentforce.core.token_event import TokenEvent
        assert dataclasses.is_dataclass(TokenEvent)


class TestTokenEventFields:
    def test_has_exactly_three_fields(self):
        from agentforce.core.token_event import TokenEvent
        fields = {f.name for f in dataclasses.fields(TokenEvent)}
        assert fields == {"tokens_in", "tokens_out", "cost_usd"}

    def test_tokens_in_is_int(self):
        from agentforce.core.token_event import TokenEvent
        f = {f.name: f for f in dataclasses.fields(TokenEvent)}
        assert f["tokens_in"].type == int

    def test_tokens_out_is_int(self):
        from agentforce.core.token_event import TokenEvent
        f = {f.name: f for f in dataclasses.fields(TokenEvent)}
        assert f["tokens_out"].type == int

    def test_cost_usd_is_float(self):
        from agentforce.core.token_event import TokenEvent
        f = {f.name: f for f in dataclasses.fields(TokenEvent)}
        assert f["cost_usd"].type == float

    def test_cost_usd_defaults_to_zero(self):
        from agentforce.core.token_event import TokenEvent
        evt = TokenEvent(tokens_in=10, tokens_out=5)
        assert evt.cost_usd == 0.0

    def test_all_fields_set(self):
        from agentforce.core.token_event import TokenEvent
        evt = TokenEvent(tokens_in=100, tokens_out=50, cost_usd=0.0025)
        assert evt.tokens_in == 100
        assert evt.tokens_out == 50
        assert evt.cost_usd == 0.0025


# ── Codex connector emits TokenEvent ─────────────────────────────────────────

class TestCodexConnectorTokenEvent:
    """Verify the Codex connector emits TokenEvent structs, not token-count strings."""

    def _make_mock_proc(self, events):
        mock_proc = MagicMock()
        mock_proc.stdout = events
        mock_proc.returncode = 0
        mock_proc.stderr.read.return_value = ""
        mock_proc.stdin = MagicMock()
        return mock_proc

    def test_turn_completed_emits_token_event_json(self, tmp_path):
        """turn.completed token counts must be returned as the 5th tuple element."""
        from agentforce.connectors import codex as cx_mod
        from agentforce.core.token_event import TokenEvent

        events = [
            '{"type":"thread.started","thread_id":"t1"}\n',
            '{"type":"turn.completed","usage":{"input_tokens":120,"output_tokens":40,"cached_input_tokens":0}}\n',
        ]
        mock_proc = self._make_mock_proc(events)

        with patch("subprocess.Popen", return_value=mock_proc):
            _, output, _, _, token_event = cx_mod.run("x", str(tmp_path))

        assert isinstance(token_event, TokenEvent)
        assert token_event.tokens_in == 120
        assert token_event.tokens_out == 40
        assert token_event.cost_usd == 0.0
        # token counts must NOT appear as JSON in the output text
        assert "token_event" not in output

    def test_no_human_readable_token_string_in_output(self, tmp_path):
        """No token-count JSON or string formatting should appear in output."""
        from agentforce.connectors import codex as cx_mod

        events = [
            '{"type":"thread.started","thread_id":"t1"}\n',
            '{"type":"turn.completed","usage":{"input_tokens":50,"output_tokens":20,"cached_input_tokens":5}}\n',
        ]
        mock_proc = self._make_mock_proc(events)

        with patch("subprocess.Popen", return_value=mock_proc):
            _, output, _, _, _ = cx_mod.run("x", str(tmp_path))

        assert "── turn complete" not in output
        assert "token_event" not in output

    def test_format_event_turn_completed_returns_token_event(self):
        """_format_event must return None for turn.completed (tokens extracted separately)."""
        from agentforce.connectors import codex as cx_mod

        event = {
            "type": "turn.completed",
            "usage": {"input_tokens": 200, "output_tokens": 80, "cached_input_tokens": 10},
        }
        result = cx_mod._format_event(event)

        assert result is None

    def test_orchestrator_receives_token_event_object(self, tmp_path):
        """Token counts from turn.completed must reach the orchestrator via 5th return element."""
        from agentforce.connectors import codex as cx_mod
        from agentforce.core.token_event import TokenEvent

        events = [
            '{"type":"thread.started","thread_id":"t2"}\n',
            '{"type":"item.completed","item":{"type":"agent_message","text":"task done"}}\n',
            '{"type":"turn.completed","usage":{"input_tokens":300,"output_tokens":100,"cached_input_tokens":0}}\n',
        ]
        mock_proc = self._make_mock_proc(events)

        with patch("subprocess.Popen", return_value=mock_proc):
            _, output, _, _, token_event = cx_mod.run("do task", str(tmp_path))

        assert isinstance(token_event, TokenEvent)
        assert token_event.tokens_in == 300
        assert token_event.tokens_out == 100
        assert "task done" in output
