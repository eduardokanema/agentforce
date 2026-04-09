"""Token usage ledger for task and mission totals."""
from __future__ import annotations

import json
from collections import defaultdict


class TokenLedger:
    """Accumulate token usage per task and across the mission."""

    def __init__(self) -> None:
        self._totals: dict[str, dict[str, float | int]] = defaultdict(
            lambda: {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
        )

    @staticmethod
    def parse_usage_line(line: str) -> dict | None:
        """Parse a usage JSON line and return token counts, or None."""
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None

        if not isinstance(payload, dict) or payload.get("type") != "usage":
            return None

        try:
            return {
                "input_tokens": int(payload["input_tokens"]),
                "output_tokens": int(payload["output_tokens"]),
                "cost_usd": float(payload["cost_usd"]),
            }
        except (KeyError, TypeError, ValueError):
            return None

    def add(self, task_id: str, tokens_in: int, tokens_out: int, cost_usd: float) -> None:
        """Accumulate usage for a task."""
        task = self._totals[task_id]
        task["tokens_in"] += int(tokens_in)
        task["tokens_out"] += int(tokens_out)
        task["cost_usd"] += float(cost_usd)

    def task_totals(self, task_id: str) -> dict:
        """Return totals for a task, or zeros if the task is unknown."""
        task = self._totals.get(task_id)
        if not task:
            return {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
        return {
            "tokens_in": task["tokens_in"],
            "tokens_out": task["tokens_out"],
            "cost_usd": task["cost_usd"],
        }

    def mission_totals(self) -> dict:
        """Return aggregate totals across all tracked tasks."""
        totals = {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
        for task in self._totals.values():
            totals["tokens_in"] += task["tokens_in"]
            totals["tokens_out"] += task["tokens_out"]
            totals["cost_usd"] += task["cost_usd"]
        return totals

    def reset_task(self, task_id: str) -> None:
        """Clear a task's accumulated usage."""
        self._totals.pop(task_id, None)
