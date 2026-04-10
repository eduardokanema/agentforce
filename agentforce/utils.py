"""Shared utility functions for AgentForce."""
from __future__ import annotations

from datetime import datetime, timezone


def fmt_duration_seconds(seconds: float | int | None) -> str:
    if seconds is None:
        return "?"
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


def fmt_duration(started_at: str | None, completed_at: str | None = None) -> str:
    """Render elapsed time as a compact human-readable string.
    """
    if not started_at:
        return "?"
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end_ts = completed_at or datetime.now(timezone.utc).isoformat()
        ended = datetime.fromisoformat(end_ts.replace("Z", "+00:00"))
        return fmt_duration_seconds((ended - started).total_seconds())
    except Exception:
        return "?"
