from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    from anthropic import Anthropic
except ModuleNotFoundError:  # pragma: no cover - exercised only in minimal test envs
    Anthropic = None

from agentforce.core.state import MissionState
from agentforce.memory.memory import Memory, MemoryEntry
from agentforce.review.collector import MetricsCollector
from agentforce.review.config import is_review_enabled
from agentforce.review.models import (
    ActionItem,
    GoodhartWarning,
    MetricsSnapshot,
    RetroItem,
    ReviewReport,
)
from agentforce.review.personas import build_persona_prompt, parse_persona_response
from agentforce.review.schemas import MissionReviewPayloadV1


AGENTFORCE_HOME = Path(os.path.expanduser("~/.agentforce"))
_MODEL_FALLBACK = "claude-sonnet-4-6"
_PERSONA_ORDER = (
    "quality_champion",
    "devils_advocate",
    "innovation_scout",
    "philosopher",
)
_METRICS_PREFIX = "review:metrics:"
_ACTION_HISTORY_KEY = "review:actions:last3"


def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _resolve_model(requested_model: str | None) -> str:
    """Resolve the model to use for review.

    Order: requested_model > connectors config > fallback 'claude-sonnet-4-6'.
    """

    if requested_model:
        return requested_model

    connectors_path = AGENTFORCE_HOME / "connectors.json"
    connectors = _load_json_file(connectors_path)
    anthropic_connector = connectors.get("anthropic")
    if isinstance(anthropic_connector, dict):
        if not anthropic_connector.get("active"):
            return _MODEL_FALLBACK
        model = anthropic_connector.get("model")
        if isinstance(model, str) and model.strip():
            return model.strip()

    return _MODEL_FALLBACK


def _get_anthropic_client() -> Anthropic:
    """Get Anthropic client. Uses ANTHROPIC_API_KEY env var (set by connector config)."""
    if Anthropic is None:
        raise ModuleNotFoundError("anthropic")
    return Anthropic()


def _response_text(response: Any) -> str:
    try:
        content = response.content
        if content and hasattr(content[0], "text"):
            return str(content[0].text)
    except Exception:
        pass
    return ""


def _usage_cost_usd(response: Any) -> float:
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0.0
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    return (input_tokens * 3 + output_tokens * 15) / 1_000_000


def _extract_json_candidate(raw: str) -> str | None:
    if not raw or not raw.strip():
        return None

    end = raw.rfind("}")
    if end == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for index in range(end, -1, -1):
        char = raw[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char == "}":
            depth += 1
            continue
        if char == "{":
            depth -= 1
            if depth == 0:
                return raw[index : end + 1]

    return None


def _load_action_history(memory: Memory, mission_id: str) -> list[str] | None:
    raw = memory.project_get(mission_id, _ACTION_HISTORY_KEY)
    if not raw:
        return None
    try:
        history = json.loads(raw)
    except Exception:
        return None
    if not isinstance(history, list):
        return None
    return [str(item) for item in history if str(item).strip()] or None


def _safe_parse_action_items(raw: str, mission_id: str) -> list[ActionItem]:
    candidate = _extract_json_candidate(raw)
    if candidate is None:
        return []

    try:
        data = json.loads(candidate)
    except Exception:
        return []

    items = data.get("action_items", [])
    if not isinstance(items, list):
        return []

    parsed: list[ActionItem] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        parsed.append(
            ActionItem(
                id=item.get("id") or f"review-{mission_id}-{index}",
                action_type=str(item.get("action_type", "")),
                title=str(item.get("title", "")),
                description=str(item.get("description", "")),
                priority=str(item.get("priority", "medium")),
                source_personas=[str(value) for value in item.get("source_personas", []) if str(value).strip()],
                source_insights=[str(value) for value in item.get("source_insights", []) if str(value).strip()],
                memory_scope=str(item.get("memory_scope", "")),
                memory_key=str(item.get("memory_key", "")),
                memory_value=str(item.get("memory_value", "")),
                memory_category=str(item.get("memory_category", "")),
            )
        )
    return parsed


class MissionReviewer:
    def __init__(
        self,
        memory: Memory,
        state_dir: Path | None = None,
        review_dir: Path | None = None,
    ):
        self.memory = memory
        self.state_dir = state_dir or (AGENTFORCE_HOME / "state")
        self.review_dir = review_dir or (AGENTFORCE_HOME / "reviews")

    def review(self, mission_id: str, model: str | None = None) -> ReviewReport:
        """Run a full review for a mission."""

        if not is_review_enabled():
            return ReviewReport(mission_id=mission_id, skipped=True)

        payload = self._load_payload(mission_id)
        metrics = MetricsCollector.collect(payload)
        baseline = self._load_baseline(mission_id)
        goodhart_warnings: list[GoodhartWarning] = []
        if baseline is not None:
            goodhart_warnings = MetricsCollector.detect_goodhart(metrics, baseline)

        prior_history = _load_action_history(self.memory, mission_id)
        resolved_model = _resolve_model(model)
        client = _get_anthropic_client()
        total_cost = 0.0
        raw_outputs: dict[str, str] = {}
        all_retro_items: list[RetroItem] = []

        for persona_key in _PERSONA_ORDER:
            system_prompt, user_prompt = build_persona_prompt(
                persona_key,
                metrics,
                payload,
                prior_history,
            )
            try:
                response = client.messages.create(
                    model=resolved_model,
                    max_tokens=2000,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                    timeout=60.0,
                )
                raw = _response_text(response)
                total_cost += _usage_cost_usd(response)
                items = parse_persona_response(raw, persona_key) if raw.strip() else []
            except Exception:
                raw = ""
                items = []
            raw_outputs[persona_key] = raw
            all_retro_items.extend(items)

        action_items, synthesis_cost = self._synthesize_actions(
            all_retro_items,
            metrics,
            client,
            resolved_model,
            mission_id,
        )
        total_cost += synthesis_cost

        report = ReviewReport(
            mission_id=mission_id,
            mission_name=payload.mission_name,
            metrics=metrics,
            goodhart_warnings=goodhart_warnings,
            retro_items=all_retro_items,
            action_items=action_items,
            raw_persona_outputs=raw_outputs,
            review_cost_usd=total_cost,
            skipped=False,
        )

        self.review_dir.mkdir(parents=True, exist_ok=True)
        report.save(self.review_dir / f"{mission_id}_review.json")
        self._save_baseline(mission_id, metrics)
        self._update_action_history(mission_id, action_items[:3])
        return report

    def _synthesize_actions(
        self,
        retro_items: list[RetroItem],
        metrics: MetricsSnapshot,
        client: Anthropic,
        model: str,
        mission_id: str,
    ) -> tuple[list[ActionItem], float]:
        """Synthesize action items from all persona insights."""

        system_prompt = (
            "You are the AgentForce review synthesizer. Convert the persona insights into "
            "structured action items. Return valid JSON only. Roadmap feature items must "
            "NOT be auto-executed. The YAML must be reviewed and approved by a human before running."
        )
        user_prompt = json.dumps(
            {
                "metrics": metrics.to_dict(),
                "retro_items": [item.to_dict() for item in retro_items],
                "action_item_schema": {
                    "action_type": "roadmap_feature|memory_entry|process_improvement",
                    "title": "...",
                    "description": "...",
                    "priority": "high|medium|low",
                    "source_personas": ["quality_champion"],
                    "source_insights": ["insight text"],
                    "memory_scope": "global|project",
                    "memory_key": "review:{mission_id}:{short_desc}",
                    "memory_value": "...",
                    "memory_category": "lesson|convention",
                },
            },
            indent=2,
        )

        try:
            response = client.messages.create(
                model=model,
                max_tokens=2000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                timeout=60.0,
            )
            raw = _response_text(response)
            cost = _usage_cost_usd(response)
            return _safe_parse_action_items(raw, mission_id), cost
        except Exception:
            return [], 0.0

    def _load_baseline(self, mission_id: str) -> MetricsSnapshot | None:
        """Load most recent metrics baseline from memory."""

        project_file = self.memory._project_file(mission_id)
        entries = self.memory._read_file(project_file)
        candidates = [entry for entry in entries if entry.key.startswith(_METRICS_PREFIX)]
        if not candidates:
            return None
        latest = sorted(candidates, key=lambda entry: entry.key, reverse=True)[0]
        try:
            return MetricsSnapshot.from_dict(json.loads(latest.value))
        except Exception:
            return None

    def _save_baseline(self, mission_id: str, metrics: MetricsSnapshot) -> None:
        """Store metrics as versioned baseline and prune old entries."""

        project_file = self.memory._project_file(mission_id)
        entries = self.memory._read_file(project_file)
        entries.append(
            MemoryEntry(
                key=f"{_METRICS_PREFIX}{metrics.computed_at}",
                value=json.dumps(metrics.to_dict()),
                category="review",
                source=mission_id,
            )
        )
        metrics_entries = [entry for entry in entries if entry.key.startswith(_METRICS_PREFIX)]
        if len(metrics_entries) > 5:
            metrics_entries = sorted(metrics_entries, key=lambda entry: entry.key, reverse=True)[:5]
        other_entries = [entry for entry in entries if not entry.key.startswith(_METRICS_PREFIX)]
        self.memory._write_file(project_file, other_entries + metrics_entries)

    def _update_action_history(self, mission_id: str, items: list[ActionItem]) -> None:
        """Store last 3 action item titles+types for injection into next review."""

        summary = [f"{item.priority} [{item.action_type}] {item.title}" for item in items[:3]]
        self.memory.project_set(mission_id, _ACTION_HISTORY_KEY, json.dumps(summary), category="review")

    def _load_payload(self, mission_id: str) -> MissionReviewPayloadV1:
        """Load MissionState JSON and convert it to the stable review payload."""

        state_path = self.state_dir / f"{mission_id}.json"
        if not state_path.exists():
            raise FileNotFoundError(state_path)
        return MissionReviewPayloadV1.from_state(MissionState.load(state_path))


__all__ = [
    "AGENTFORCE_HOME",
    "MissionReviewer",
    "_get_anthropic_client",
    "_resolve_model",
]
