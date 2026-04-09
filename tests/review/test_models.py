from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agentforce.core.spec import Caps
from agentforce.review import (
    ActionItem,
    GoodhartWarning,
    MetricsSnapshot,
    ReviewReport,
    RetroItem,
)
from agentforce.review.config import is_review_enabled


def test_metrics_snapshot_round_trip_and_quality_score():
    snapshot = MetricsSnapshot(
        mission_id="mission-1",
        token_efficiency=12.5,
        first_pass_rate=0.8,
        rework_rate=0.2,
        avg_review_score=7.5,
        human_escalation_rate=0.1,
        wall_time_per_task_s=42.0,
        cost_per_task_usd=3.25,
        review_rejection_rate=0.05,
        data_quality_warnings=["missing_review"],
        tasks_completed=4,
        tasks_total=5,
        total_retries=2,
        total_human_interventions=1,
        total_cost_usd=13.0,
        total_tokens_out=1000,
        total_wall_time_s=168.0,
    )

    expected_quality = ((7.5 / 10) * 0.4 + 0.8 * 0.25 + (1 - 0.1) * 0.3) * 10
    assert snapshot.quality_score == pytest.approx(expected_quality)

    restored = MetricsSnapshot.from_dict(snapshot.to_dict())
    assert restored == snapshot


def test_review_report_round_trip_and_save_load(tmp_path):
    report = ReviewReport(
        mission_id="mission-1",
        mission_name="Demo mission",
        metrics=MetricsSnapshot(
            mission_id="mission-1",
            avg_review_score=8.0,
            first_pass_rate=0.75,
            human_escalation_rate=0.2,
        ),
        goodhart_warnings=[
            GoodhartWarning(
                metric_name="token_efficiency",
                metric_direction="improved",
                quality_direction="degraded",
                message="Token efficiency improved but quality dropped",
                baseline_quality=8.0,
                current_quality=6.0,
                baseline_metric=10.0,
                current_metric=20.0,
            )
        ],
        retro_items=[
            RetroItem(
                persona="quality_champion",
                category="went_well",
                insight="Good code structure",
                supporting_evidence=["reviewed cleanly"],
                confidence=0.9,
            )
        ],
        action_items=[
            ActionItem(
                id="a-1",
                action_type="memory_entry",
                title="Capture lesson",
                description="Record a reusable lesson",
                priority="high",
                source_personas=["quality_champion"],
                source_insights=["good code structure"],
                approved=True,
                memory_scope="global",
                memory_key="lesson.reviewing",
                memory_value="Prefer explicit tests",
                memory_category="lesson",
            )
        ],
        raw_persona_outputs={"quality_champion": "{\"approved\": true}"},
        review_cost_usd=1.5,
        skipped=False,
    )

    restored = ReviewReport.from_dict(report.to_dict())
    assert restored == report

    path = tmp_path / "nested" / "report.json"
    report.save(path)
    assert path.exists()
    assert json.loads(path.read_text())["mission_id"] == "mission-1"
    assert ReviewReport.load(path) == report


def test_caps_review_field_serializes_round_trip():
    caps = Caps(review="disabled")
    data = caps.to_dict()
    assert data["review"] == "disabled"
    restored = Caps.from_dict(data)
    assert restored == caps


def test_is_review_enabled_respects_config_file(tmp_path, monkeypatch):
    config_home = tmp_path / ".agentforce"
    config_home.mkdir()
    monkeypatch.setattr("agentforce.review.config.AGENTFORCE_HOME", config_home)
    (config_home / "config.json").write_text(json.dumps({"review_enabled": False}))

    assert is_review_enabled() is False
