from __future__ import annotations

import json
from typing import Any

from agentforce.review.models import MetricsSnapshot, RetroItem
from agentforce.review.schemas import MissionReviewPayloadV1

PERSONA_CONFIGS: dict[str, dict] = {
    "quality_champion": {
        "category": "went_well",
        "display_name": "Quality Champion",
        "system_prompt": """You are the Quality Champion in an AgentForce mission retrospective.
Your role is to identify what went WELL. Focus on:
- Tasks that passed review on the first attempt (0 retries, high score)
- Patterns in acceptance criteria that were well-specified
- Memory context or agent instructions that helped workers succeed
- High review scores (>= 8/10) — what made the reviewer approve?
- TDD patterns that caught issues early

Analyze the mission data below. Produce 3-5 specific insights grounded in the data.
For each, cite the specific task ID, metric value, or event log entry as evidence.
Do NOT produce generic advice. Every insight must reference actual numbers or events.

RESPOND WITH VALID JSON ONLY — no prose before or after:
{"insights": [{"insight": "...", "supporting_evidence": ["task_id:01 score=9 retries=0", "..."], "confidence": 0.9}]}""",
    },
    "devils_advocate": {
        "category": "not_well",
        "display_name": "Devil's Advocate",
        "system_prompt": """You are the Devil's Advocate in an AgentForce mission retrospective.
Your role is to identify what did NOT go well. Focus on:
- Tasks that required retries: what caused the worker to fail?
- Low review scores (< 7): what patterns in review feedback indicate?
- Human escalations: what did the agent fail to handle autonomously?
- Caps that were hit: what resource constraints caused problems?
- Blocking issues in review_feedback: recurring patterns?

Analyze the mission data below. Produce 3-5 specific insights grounded in the data.
For each, cite the specific task ID, metric value, or event log entry as evidence.
Do NOT produce generic advice. Every insight must reference actual numbers or events.

RESPOND WITH VALID JSON ONLY — no prose before or after:
{"insights": [{"insight": "...", "supporting_evidence": ["task_id:02 retries=3", "..."], "confidence": 0.85}]}""",
    },
    "innovation_scout": {
        "category": "should_try",
        "display_name": "Innovation Scout",
        "system_prompt": """You are the Innovation Scout in an AgentForce mission retrospective.
Your role is to propose actionable experiments. Focus on:
- Cap adjustments: would higher/lower retry limits, wall time, or concurrency help?
- Task granularity: should large tasks be split to reduce rework?
- Acceptance criteria improvements: what made criteria hard to verify?
- Memory entries: what lessons should be stored to prevent repeated mistakes?
- Model selection: are expensive models used where cheaper ones would suffice?

Analyze the mission data below. Produce 3-5 specific, testable proposals.
Each must be actionable and reference data from this mission (not generic advice).

RESPOND WITH VALID JSON ONLY — no prose before or after:
{"insights": [{"insight": "proposal", "supporting_evidence": ["rework_rate=0.6", "..."], "confidence": 0.7}]}""",
    },
    "philosopher": {
        "category": "puzzles_us",
        "display_name": "Philosopher",
        "system_prompt": """You are the Philosopher in an AgentForce mission retrospective.
Your role is to surface anomalies, paradoxes, and unexplained patterns. Focus on:
- Tasks with high review scores but many retries (or vice versa): why?
- Metrics that contradict each other (e.g., low cost but high wall time)
- Human escalations that seem avoidable in retrospect
- Event log sequences that suggest systemic issues (e.g., always failing on task N)
- Correlations between token usage and quality that defy expectations

Analyze the mission data below. Produce 2-4 thought-provoking puzzles.
Frame each as a question or anomaly worth investigating further.

RESPOND WITH VALID JSON ONLY — no prose before or after:
{"insights": [{"insight": "puzzle or anomaly", "supporting_evidence": ["..."], "confidence": 0.6}]}""",
    },
}

_METRIC_FIELDS: tuple[str, ...] = (
    "token_efficiency",
    "first_pass_rate",
    "rework_rate",
    "avg_review_score",
    "human_escalation_rate",
    "wall_time_per_task_s",
    "cost_per_task_usd",
    "review_rejection_rate",
)


def _format_number(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, float):
        text = f"{value:.4f}".rstrip("0").rstrip(".")
        return text if text else "0"
    return str(value)


def _format_metric_row(metrics: MetricsSnapshot, field_name: str) -> str:
    value = getattr(metrics, field_name)
    baseline = getattr(metrics, f"baseline_{field_name}", None)
    if isinstance(baseline, (int, float)) and baseline not in (None, 0):
        delta = value - baseline
        direction = "↓" if delta <= 0 else "↑"
        return f"{field_name} | {_format_number(value)} ({direction}{_format_number(abs(delta))} vs baseline)"
    return f"{field_name} | {_format_number(value)}"


def _truncate_title(title: str, limit: int = 40) -> str:
    if len(title) <= limit:
        return title
    return title[: limit - 3] + "..."


def build_persona_prompt(
    persona_key: str,
    metrics: MetricsSnapshot,
    payload: MissionReviewPayloadV1,
    prior_history: list[str] | None = None,
) -> tuple[str, str]:
    """Build (system_prompt, user_message) for a persona."""
    config = PERSONA_CONFIGS[persona_key]

    lines: list[str] = [
        f"Mission: {payload.mission_name}",
        f"Goal: {payload.mission_goal[:200]}",
        f"completed_at: {payload.completed_at if payload.completed_at is not None else 'None'}",
        "",
        "Metrics table:",
        "metric | value",
    ]
    for field_name in _METRIC_FIELDS:
        lines.append(_format_metric_row(metrics, field_name))
    lines.append(f"quality_score | {_format_number(metrics.quality_score)}")
    lines.append(
        f"efficiency_gated | {_format_number(metrics.efficiency_gated) if metrics.efficiency_gated is not None else 'none'}"
    )

    lines.extend(
        [
            "",
            "Per-task breakdown:",
            "task_id | title | status | retries | score | cost_usd | tokens_out",
        ]
    )
    for task in payload.tasks:
        title = _truncate_title(task.title)
        status = task.status
        retries = task.retries
        score = task.review_score
        cost = task.cost_usd
        tokens_out = task.tokens_out
        lines.append(
            f"{task.task_id} | {title} | {status} | {retries} | {score} | {_format_number(cost)} | {tokens_out}"
        )

    lines.extend(
        [
            "",
            "Last 50 event_log entries:",
            "timestamp | event_type | task_id | details",
        ]
    )
    for entry in payload.event_log[-50:]:
        lines.append(
            f"{entry.timestamp} | {entry.event_type} | {entry.task_id or '-'} | {entry.details}"
        )

    if payload.caps_hit:
        lines.append("")
        lines.append("Caps hit:")
        for cap, description in payload.caps_hit.items():
            lines.append(f"caps_hit: {cap}: {description}")

    if prior_history:
        lines.append("")
        lines.append(
            f"Prior 3 action items from last review: [{', '.join(prior_history[:3])}]"
        )

    return config["system_prompt"], "\n".join(lines)


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


def parse_persona_response(raw: str, persona_key: str) -> list[RetroItem]:
    """Parse Claude's JSON response into list[RetroItem]."""
    category = PERSONA_CONFIGS[persona_key]["category"]

    try:
        candidate = _extract_json_candidate(raw)
        if candidate is None:
            raise ValueError("No JSON object found")

        data = json.loads(candidate)
        insights = data["insights"]
        if not isinstance(insights, list):
            raise ValueError("insights must be a list")

        parsed: list[RetroItem] = []
        for insight in insights:
            if not isinstance(insight, dict):
                raise ValueError("insight entries must be objects")
            supporting_evidence = insight.get("supporting_evidence", [])
            if not isinstance(supporting_evidence, list):
                raise ValueError("supporting_evidence must be a list")
            parsed.append(
                RetroItem(
                    persona=persona_key,
                    category=category,
                    insight=str(insight.get("insight", "")),
                    supporting_evidence=[str(item) for item in supporting_evidence],
                    confidence=float(insight.get("confidence", 0.5)),
                )
            )
        return parsed
    except Exception:
        return [
            RetroItem(
                persona=persona_key,
                category=category,
                insight=raw[:500],
                confidence=0.3,
            )
        ]


__all__ = ["PERSONA_CONFIGS", "build_persona_prompt", "parse_persona_response"]
