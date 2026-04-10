"""Helpers for worker-originated destructive-action approval requests."""
from __future__ import annotations

import json
import re
from typing import Any


DESTRUCTIVE_ACTION_KIND = "destructive_action"
DESTRUCTIVE_ACTION_REQUEST_TYPE = "destructive_action_request"

DESTRUCTIVE_ACTION_OPTIONS: list[dict[str, str]] = [
    {
        "id": "approve_once",
        "label": "Approve once",
        "description": "Allow this action for the next worker attempt only.",
        "effect": "retry_with_approval",
    },
    {
        "id": "always_allow",
        "label": "Always allow this exact action",
        "description": "Allow future matching requests in this mission by exact action key.",
        "effect": "store_mission_allow_rule",
    },
    {
        "id": "deny",
        "label": "Deny",
        "description": "Tell the worker not to perform the action and to find a safer path.",
        "effect": "retry_without_action",
    },
    {
        "id": "revise",
        "label": "Revise with instructions",
        "description": "Provide alternate instructions for the next worker attempt.",
        "effect": "retry_with_operator_guidance",
    },
]

_FENCE_RE = re.compile(r"```(?P<label>agentforce-warning|json)?\s*\n(?P<body>.*?)```", re.DOTALL)


def _clean_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _normalize_targets(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    targets = []
    for item in value:
        if isinstance(item, str) and item.strip():
            targets.append(item.strip())
    return targets


def _normalize_request(data: Any) -> dict | None:
    if not isinstance(data, dict):
        return None
    if data.get("type") != DESTRUCTIVE_ACTION_REQUEST_TYPE:
        return None

    summary = _clean_string(data.get("summary"))
    risk = _clean_string(data.get("risk"))
    proposed_action = _clean_string(data.get("proposed_action"))
    action_key = _clean_string(data.get("action_key"))
    if not summary or not risk or not proposed_action or not action_key:
        return None

    return {
        "type": DESTRUCTIVE_ACTION_REQUEST_TYPE,
        "summary": summary,
        "risk": risk,
        "proposed_action": proposed_action,
        "targets": _normalize_targets(data.get("targets")),
        "action_key": action_key,
    }


def _parse_json_object(raw: str) -> dict | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def parse_destructive_action_request(output: str) -> dict | None:
    """Extract a worker destructive-action warning from output, if present."""
    if not isinstance(output, str) or DESTRUCTIVE_ACTION_REQUEST_TYPE not in output:
        return None

    matches = list(_FENCE_RE.finditer(output))
    for match in reversed(matches):
        label = (match.group("label") or "").strip()
        if label not in {"agentforce-warning", "json"}:
            continue
        normalized = _normalize_request(_parse_json_object(match.group("body").strip()))
        if normalized:
            return normalized

    decoder = json.JSONDecoder()
    for idx in range(len(output) - 1, -1, -1):
        if output[idx] != "{":
            continue
        try:
            data, _ = decoder.raw_decode(output[idx:])
        except json.JSONDecodeError:
            continue
        normalized = _normalize_request(data)
        if normalized:
            return normalized

    return None
