from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agentforce.core.spec import Caps, MissionSpec, TaskSpec, TaskStatus
from agentforce.core.state import EventLogEntry, MissionState, TaskState
from agentforce.memory.memory import Memory
from agentforce.review.models import ReviewReport
from agentforce.review.reviewer import MissionReviewer, _resolve_model


def _persona_json(label: str) -> str:
    return json.dumps(
        {
            "insights": [
                {
                    "insight": f"{label} insight",
                    "supporting_evidence": [f"{label}:evidence"],
                    "confidence": 0.9,
                }
            ]
        }
    )


class MockUsage:
    input_tokens = 1000
    output_tokens = 500


class MockResponse:
    def __init__(self, text: str):
        self.content = [type("Chunk", (), {"text": text})()]
        self.usage = MockUsage()


class MockAnthropicClient:
    def __init__(self, failing_call: int | None = None):
        self.calls: list[dict] = []
        self.failing_call = failing_call

    class _Messages:
        def __init__(self, outer: "MockAnthropicClient"):
            self.outer = outer

        def create(self, **kwargs):
            self.outer.calls.append(kwargs)
            if self.outer.failing_call is not None and len(self.outer.calls) == self.outer.failing_call:
                raise RuntimeError("persona failure")
            call_index = len(self.outer.calls)
            if call_index <= 4:
                return MockResponse(_persona_json(f"persona-{call_index}"))
            return MockResponse(
                json.dumps(
                    {
                        "action_items": [
                            {
                                "action_type": "memory_entry",
                                "title": "Capture the lesson",
                                "description": "Store the key review lesson.",
                                "priority": "high",
                                "source_personas": ["quality_champion"],
                                "source_insights": ["persona-1 insight"],
                                "memory_scope": "project",
                                "memory_key": "review:mission-123:capture-lesson",
                                "memory_value": "Store the key review lesson.",
                                "memory_category": "lesson",
                            }
                        ]
                    }
                )
            )

    @property
    def messages(self):
        return self._Messages(self)


@pytest.fixture
def mission_state(tmp_path: Path) -> MissionState:
    spec = MissionSpec(
        name="Reviewer Mission",
        goal="Validate the reviewer orchestration slice.",
        definition_of_done=["review report generated"],
        tasks=[
            TaskSpec(id="01", title="First task", description="Do the first thing."),
            TaskSpec(id="02", title="Second task", description="Do the second thing."),
        ],
        caps=Caps(max_concurrent_workers=2, max_retries_global=4, max_wall_time_minutes=90),
    )
    state = MissionState(
        mission_id="mission-123",
        spec=spec,
        completed_at="2026-04-09T01:00:00+00:00",
        total_retries=1,
        total_human_interventions=0,
        tokens_in=1200,
        tokens_out=2200,
        cost_usd=12.0,
    )
    state.task_states = {
        "01": TaskState(
            task_id="01",
            spec_summary="First task",
            status=TaskStatus.REVIEW_APPROVED,
            retries=0,
            review_score=9,
            tokens_out=800,
            cost_usd=2.0,
        ),
        "02": TaskState(
            task_id="02",
            spec_summary="Second task",
            status=TaskStatus.RETRY,
            retries=1,
            review_score=6,
            tokens_out=1400,
            cost_usd=10.0,
        ),
    }
    state.event_log = [
        EventLogEntry(
            timestamp="2026-04-09T00:00:01+00:00",
            event_type="task_completed",
            task_id="01",
            details="task 01 done",
        ),
        EventLogEntry(
            timestamp="2026-04-09T00:00:02+00:00",
            event_type="review_approved",
            task_id="01",
            details="approved",
        ),
    ]

    state_path = tmp_path / "state" / "mission-123.json"
    state.save(state_path)
    return state


def test_review_runs_full_flow_and_persists_results(tmp_path: Path, mission_state: MissionState):
    memory = Memory(tmp_path / "memory")
    review_dir = tmp_path / "reviews"
    state_dir = tmp_path / "state"
    connectors_dir = tmp_path / ".agentforce"
    connectors_dir.mkdir(parents=True, exist_ok=True)
    (connectors_dir / "connectors.json").write_text(
        json.dumps({"anthropic": {"active": True, "model": "claude-sonnet-4-6"}})
    )

    client = MockAnthropicClient()
    with patch("agentforce.review.reviewer.AGENTFORCE_HOME", connectors_dir), patch(
        "agentforce.review.reviewer.Anthropic", return_value=client
    ):
        reviewer = MissionReviewer(memory=memory, state_dir=state_dir, review_dir=review_dir)
        report = reviewer.review("mission-123")

    assert isinstance(report, ReviewReport)
    assert report.metrics is not None
    assert report.goodhart_warnings is not None
    assert len(report.retro_items) >= 4
    assert len(report.action_items) >= 1
    assert report.raw_persona_outputs.keys() == {
        "quality_champion",
        "devils_advocate",
        "innovation_scout",
        "philosopher",
    }
    assert report.review_cost_usd > 0
    assert len(client.calls) == 5
    assert client.calls[0]["model"] == "claude-sonnet-4-6"

    saved = review_dir / "mission-123_review.json"
    assert saved.exists()
    loaded = ReviewReport.load(saved)
    assert loaded == report

    stored = memory.project_get("mission-123", "review:actions:last3")
    assert stored is not None
    assert "Capture the lesson" in stored

    project_file = memory._project_file("mission-123")
    assert project_file.exists()
    contents = project_file.read_text()
    assert "review:metrics:" in contents


def test_review_uses_prior_history_on_second_run(tmp_path: Path, mission_state: MissionState):
    memory = Memory(tmp_path / "memory")
    review_dir = tmp_path / "reviews"
    state_dir = tmp_path / "state"
    connectors_dir = tmp_path / ".agentforce"
    connectors_dir.mkdir(parents=True, exist_ok=True)
    (connectors_dir / "connectors.json").write_text(
        json.dumps({"anthropic": {"active": True, "model": "claude-sonnet-4-6"}})
    )

    client = MockAnthropicClient()
    with patch("agentforce.review.reviewer.AGENTFORCE_HOME", connectors_dir), patch(
        "agentforce.review.reviewer.Anthropic", return_value=client
    ):
        reviewer = MissionReviewer(memory=memory, state_dir=state_dir, review_dir=review_dir)
        reviewer.review("mission-123")
        first_prompt = client.calls[0]["messages"][0]["content"]

        client.calls.clear()
        reviewer.review("mission-123")
        second_prompt = client.calls[0]["messages"][0]["content"]

    assert "Prior 3 action items from last review" not in first_prompt
    assert "Prior 3 action items from last review" in second_prompt
    assert "high [memory_entry] Capture the lesson" in second_prompt


def test_review_continues_when_one_persona_fails(tmp_path: Path, mission_state: MissionState):
    memory = Memory(tmp_path / "memory")
    review_dir = tmp_path / "reviews"
    state_dir = tmp_path / "state"
    connectors_dir = tmp_path / ".agentforce"
    connectors_dir.mkdir(parents=True, exist_ok=True)
    (connectors_dir / "connectors.json").write_text(
        json.dumps({"anthropic": {"active": True, "model": "claude-sonnet-4-6"}})
    )

    client = MockAnthropicClient(failing_call=2)
    with patch("agentforce.review.reviewer.AGENTFORCE_HOME", connectors_dir), patch(
        "agentforce.review.reviewer.Anthropic", return_value=client
    ):
        reviewer = MissionReviewer(memory=memory, state_dir=state_dir, review_dir=review_dir)
        report = reviewer.review("mission-123")

    assert isinstance(report, ReviewReport)
    assert len(client.calls) == 5
    assert report.raw_persona_outputs["devils_advocate"] == ""
    assert report.action_items


def test_resolve_model_ignores_inactive_anthropic_connector(tmp_path: Path, monkeypatch):
    connectors_dir = tmp_path / ".agentforce"
    connectors_dir.mkdir(parents=True, exist_ok=True)
    (connectors_dir / "connectors.json").write_text(
        json.dumps({"anthropic": {"active": False, "model": "claude-sonnet-4-6"}})
    )

    monkeypatch.setattr("agentforce.review.reviewer.AGENTFORCE_HOME", connectors_dir)

    assert _resolve_model(None) == "claude-sonnet-4-5"


def test_review_respects_global_opt_out(tmp_path: Path, mission_state: MissionState):
    memory = Memory(tmp_path / "memory")
    review_dir = tmp_path / "reviews"
    state_dir = tmp_path / "state"
    connectors_dir = tmp_path / ".agentforce"
    connectors_dir.mkdir(parents=True, exist_ok=True)
    (connectors_dir / "connectors.json").write_text(
        json.dumps({"anthropic": {"active": True, "model": "claude-sonnet-4-6"}})
    )

    client = MockAnthropicClient()
    with patch("agentforce.review.reviewer.AGENTFORCE_HOME", connectors_dir), patch(
        "agentforce.review.reviewer.Anthropic", return_value=client
    ), patch("agentforce.review.reviewer.is_review_enabled", return_value=False, create=True):
        reviewer = MissionReviewer(memory=memory, state_dir=state_dir, review_dir=review_dir)
        report = reviewer.review("mission-123")

    assert report.skipped is True
    assert report.metrics is None
    assert client.calls == []
    assert not (review_dir / "mission-123_review.json").exists()
