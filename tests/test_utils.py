"""Tests for shared utility helpers."""
from agentforce.utils import fmt_duration


def test_fmt_duration_handles_missing_started_at():
    assert fmt_duration(None, None) == "?"
