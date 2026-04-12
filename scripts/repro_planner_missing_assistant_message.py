#!/usr/bin/env python3
"""Reproduce planner parsing failure when the model omits assistant_message."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agentforce.server import planner_adapter


RESPONSE_TEXT = """
I’m checking the mission-spec shape before returning the updated draft.
{"name":"Weather Mission","goal":"Return the current weather conditions for an Australian city.","definition_of_done":["Page returns current conditions for a selected Australian city."],"tasks":[],"caps":{}}
""".strip()


def main() -> int:
    try:
        assistant_message, draft_spec = planner_adapter._parse_planner_response(RESPONSE_TEXT)
    except Exception as exc:  # pragma: no cover - this script is for manual repro.
        print(f"repro failed: {exc}", file=sys.stderr)
        return 1

    print(f"assistant_message={assistant_message}")
    print(f"name={draft_spec.get('name')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
