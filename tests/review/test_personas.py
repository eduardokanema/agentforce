from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agentforce.core.spec import Caps, MissionSpec, TaskSpec, TaskStatus
from agentforce.core.state import EventLogEntry, MissionState, TaskState
from agentforce.review.models import MetricsSnapshot, RetroItem
from agentforce.review.personas import (
    PERSONA_CONFIGS,
    build_persona_prompt,
    parse_persona_response,
)
from agentforce.review.schemas import MissionReviewPayloadV1


@pytest.fixture
def mission_payload() -> MissionReviewPayloadV1:
    spec = MissionSpec(
        name="Persona Review Mission",
        goal="Deliver a reliable review slice with strong prompt formatting and parsing.",
        definition_of_done=["All persona outputs parsed", "Prompt includes mission context"],
        tasks=[
            TaskSpec(id="01", title="Implement parser", description="Build the response parser."),
            TaskSpec(id="02", title="Format prompt", description="Render the mission prompt."),
        ],
        caps=Caps(max_concurrent_workers=2, max_retries_global=4, max_wall_time_minutes=90),
    )
    state = MissionState(
        mission_id="mission-123",
        spec=spec,
        completed_at="2026-04-09T01:00:00+00:00",
        total_retries=3,
        total_human_interventions=1,
        tokens_in=1000,
        tokens_out=2500,
        cost_usd=12.34,
        caps_hit={"wall_time": "Wall time limit exceeded"},
    )
    state.task_states = {
        "01": TaskState(
            task_id="01",
            spec_summary="Implement parser",
            status=TaskStatus.REVIEW_APPROVED,
            retries=0,
            review_score=9,
            cost_usd=1.23,
            tokens_out=400,
        ),
        "02": TaskState(
            task_id="02",
            spec_summary="Format prompt",
            status=TaskStatus.RETRY,
            retries=2,
            review_score=6,
            cost_usd=2.5,
            tokens_out=800,
        ),
    }
    state.event_log = [
        EventLogEntry(timestamp=f"2026-04-09T00:00:{i:02d}+00:00", event_type="task_event", task_id="01", details=f"log-{i:02d}")
        for i in range(1, 53)
    ]
    return MissionReviewPayloadV1.from_state(state)


def test_persona_configs_have_expected_keys():
    assert set(PERSONA_CONFIGS) == {
        "quality_champion",
        "devils_advocate",
        "innovation_scout",
        "philosopher",
    }
    for persona_key, config in PERSONA_CONFIGS.items():
        assert "category" in config
        assert "display_name" in config
        assert "system_prompt" in config
        assert "RESPOND WITH VALID JSON" in config["system_prompt"]


@pytest.mark.parametrize("persona_key", sorted(PERSONA_CONFIGS))
def test_build_persona_prompt_includes_required_sections(persona_key: str, mission_payload: MissionReviewPayloadV1):
    metrics = MetricsSnapshot(
        mission_id=mission_payload.mission_id,
        token_efficiency=12.5,
        first_pass_rate=0.8,
        rework_rate=0.2,
        avg_review_score=7.5,
        human_escalation_rate=0.1,
        wall_time_per_task_s=42.0,
        cost_per_task_usd=3.25,
        review_rejection_rate=0.05,
        efficiency_gated=11.0,
        data_quality_warnings=["missing_review"],
        tasks_completed=1,
        tasks_total=2,
        total_retries=2,
        total_human_interventions=1,
        total_cost_usd=3.73,
        total_tokens_out=1200,
        total_wall_time_s=84.0,
    )

    system_prompt, user_message = build_persona_prompt(
        persona_key=persona_key,
        metrics=metrics,
        payload=mission_payload,
        prior_history=["Tighten acceptance criteria", "Add parser regression tests"],
    )

    assert system_prompt.strip()
    assert user_message.strip()
    assert "Mission: Persona Review Mission" in user_message
    assert "Deliver a reliable review slice" in user_message
    assert "completed_at: 2026-04-09T01:00:00+00:00" in user_message
    assert "token_efficiency" in user_message
    assert "12.5" in user_message
    assert "quality_score" in user_message
    assert "efficiency_gated" in user_message
    assert "01 | Implement parser" in user_message
    assert "02 | Format prompt" in user_message
    assert "review_approved" in user_message
    assert "retry" in user_message
    assert sum(1 for line in user_message.splitlines() if "task_event" in line) == 50
    assert "log-01" not in user_message
    assert "log-02" not in user_message
    assert "log-03" in user_message
    assert "log-52" in user_message
    assert "caps_hit: wall_time: Wall time limit exceeded" in user_message
    assert "Prior 3 action items from last review" in user_message
    assert "Tighten acceptance criteria" in user_message


def test_build_persona_prompt_omits_prior_history_when_absent(mission_payload: MissionReviewPayloadV1):
    metrics = MetricsSnapshot(mission_id=mission_payload.mission_id)

    _, user_message = build_persona_prompt("quality_champion", metrics, mission_payload, prior_history=None)

    assert "Prior 3 action items from last review" not in user_message


@pytest.mark.parametrize("persona_key", sorted(PERSONA_CONFIGS))
def test_parse_persona_response_valid_json(persona_key: str):
    raw = json.dumps(
        {
            "insights": [
                {
                    "insight": "Task 01 passed on the first attempt with score 9.",
                    "supporting_evidence": ["task_id:01 score=9 retries=0"],
                    "confidence": 0.95,
                }
            ]
        }
    )

    parsed = parse_persona_response(raw, persona_key)

    assert parsed == [
        RetroItem(
            persona=persona_key,
            category=PERSONA_CONFIGS[persona_key]["category"],
            insight="Task 01 passed on the first attempt with score 9.",
            supporting_evidence=["task_id:01 score=9 retries=0"],
            confidence=0.95,
        )
    ]


def test_parse_persona_response_extracts_embedded_json():
    raw = (
        "Here is the retrospective output.\n"
        "{\"insights\": [{\"insight\": \"Retry count was high.\", "
        "\"supporting_evidence\": [\"task_id:02 retries=2\"], \"confidence\": 0.7}]}\n"
        "Extra prose that should be ignored."
    )

    parsed = parse_persona_response(raw, "devils_advocate")

    assert parsed == [
        RetroItem(
            persona="devils_advocate",
            category=PERSONA_CONFIGS["devils_advocate"]["category"],
            insight="Retry count was high.",
            supporting_evidence=["task_id:02 retries=2"],
            confidence=0.7,
        )
    ]


@pytest.mark.parametrize("raw", ["{not valid json", "", "no json at all"])
def test_parse_persona_response_falls_back_on_malformed_output(raw: str):
    parsed = parse_persona_response(raw, "philosopher")

    assert parsed == [
        RetroItem(
            persona="philosopher",
            category=PERSONA_CONFIGS["philosopher"]["category"],
            insight=raw[:500],
            confidence=0.3,
        )
    ]
