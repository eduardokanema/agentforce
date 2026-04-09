from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from agentforce.cli import cli
from agentforce.core.spec import Caps, MissionSpec, TaskSpec, TaskStatus
from agentforce.core.state import MissionState, TaskState
from agentforce.review.models import ActionItem, MetricsSnapshot, ReviewReport
from agentforce.server.handler import DashboardHandler


def _make_state(mission_id: str = "mission-123") -> MissionState:
    spec = MissionSpec(
        name="Integration Mission",
        goal="Exercise review integration routes",
        definition_of_done=["Review routing works"],
        tasks=[
            TaskSpec(
                id="task-1",
                title="First task",
                description="Exercise review integration",
            )
        ],
        caps=Caps(max_concurrent_workers=1),
    )
    return MissionState(
        mission_id=mission_id,
        spec=spec,
        task_states={
            "task-1": TaskState(
                task_id="task-1",
                spec_summary="Exercise review integration",
                status=TaskStatus.REVIEW_APPROVED,
            )
        },
        started_at="2026-04-09T00:00:00+00:00",
    )


def _make_report(mission_id: str = "mission-123") -> ReviewReport:
    return ReviewReport(
        mission_id=mission_id,
        mission_name="Integration Mission",
        metrics=MetricsSnapshot(
            mission_id=mission_id,
            token_efficiency=42.0,
            first_pass_rate=0.5,
            rework_rate=0.25,
            avg_review_score=8.0,
            human_escalation_rate=0.1,
            wall_time_per_task_s=60.0,
            cost_per_task_usd=1.25,
            review_rejection_rate=0.05,
            data_quality_warnings=["missing review metadata"],
            tasks_completed=1,
            tasks_total=1,
            total_retries=1,
            total_human_interventions=0,
            total_cost_usd=1.25,
            total_tokens_out=1000,
            total_wall_time_s=60.0,
        ),
        action_items=[
            ActionItem(
                id="a-1",
                action_type="memory_entry",
                title="Capture lesson",
                description="Keep the lesson",
                priority="high",
                source_personas=["quality_champion"],
                source_insights=["keep the lesson"],
                approved=True,
                memory_scope="project",
                memory_key="review:lesson",
                memory_value="Keep the lesson",
                memory_category="lesson",
            )
        ],
        review_cost_usd=2.5,
    )


class _Args:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _make_handler(path: str, body: bytes = b"") -> DashboardHandler:
    handler = object.__new__(DashboardHandler)
    handler.path = path
    handler.headers = {"Content-Length": str(len(body))}
    handler.connection = object()
    handler.rfile = BytesIO(body)
    handler.wfile = BytesIO()
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    handler._html = MagicMock()
    handler._err = MagicMock()
    return handler


def _response_body(handler: DashboardHandler) -> dict | list:
    return json.loads(handler.wfile.getvalue().decode("utf-8"))


def test_cli_review_skip_writes_sentinel_file_and_prints_message(tmp_path: Path, monkeypatch, capsys):
    home = tmp_path / ".agentforce"
    state_dir = home / "state"
    memory_dir = home / "memory"
    reviews_dir = home / "reviews"
    state_dir.mkdir(parents=True)
    memory_dir.mkdir(parents=True)
    _make_state().save(state_dir / "mission-123.json")

    monkeypatch.setattr(cli, "AGENTFORCE_HOME", home)
    monkeypatch.setattr(cli, "STATE_DIR", state_dir)
    monkeypatch.setattr(cli, "MEMORY_DIR", memory_dir)

    cli.cmd_review(_Args(id="mission-123", model=None, approve=False, skip=True))

    out = capsys.readouterr().out
    assert "Review skipped for mission mission-123" in out
    assert (reviews_dir / "mission-123_skipped").exists()


def test_cli_review_approve_writes_approved_items(tmp_path: Path, monkeypatch, capsys):
    home = tmp_path / ".agentforce"
    state_dir = home / "state"
    memory_dir = home / "memory"
    state_dir.mkdir(parents=True)
    memory_dir.mkdir(parents=True)
    _make_state().save(state_dir / "mission-123.json")

    monkeypatch.setattr(cli, "AGENTFORCE_HOME", home)
    monkeypatch.setattr(cli, "STATE_DIR", state_dir)
    monkeypatch.setattr(cli, "MEMORY_DIR", memory_dir)

    report = _make_report()
    reviewer = MagicMock()
    reviewer.review.return_value = report
    writer = MagicMock()
    writer.approve_all.return_value = 1
    writer.write_approved_items.return_value = 1

    with patch("agentforce.review.reviewer.MissionReviewer", return_value=reviewer), patch(
        "agentforce.review.memory_writer.ReviewMemoryWriter", return_value=writer
    ):
        cli.cmd_review(_Args(id="mission-123", model="claude", approve=True, skip=False))

    out = capsys.readouterr().out
    assert "Approved and wrote 1 action items to memory." in out
    writer.approve_all.assert_called_once_with(report)
    writer.write_approved_items.assert_called_once_with(report)


def test_cli_review_prints_metric_sections(tmp_path: Path, monkeypatch, capsys):
    home = tmp_path / ".agentforce"
    state_dir = home / "state"
    memory_dir = home / "memory"
    state_dir.mkdir(parents=True)
    memory_dir.mkdir(parents=True)
    _make_state().save(state_dir / "mission-123.json")

    monkeypatch.setattr(cli, "AGENTFORCE_HOME", home)
    monkeypatch.setattr(cli, "STATE_DIR", state_dir)
    monkeypatch.setattr(cli, "MEMORY_DIR", memory_dir)

    report = _make_report()
    reviewer = MagicMock()
    reviewer.review.return_value = report

    with patch("agentforce.review.reviewer.MissionReviewer", return_value=reviewer):
        cli.cmd_review(_Args(id="mission-123", model=None, approve=False, skip=False))

    out = capsys.readouterr().out
    assert "=== Mission Review: Integration Mission ===" in out
    assert "Quality Score:" in out
    assert "First-Pass Rate:" in out
    assert "Rework Rate:" in out
    assert "Avg Review Score:" in out
    assert "Human Escalation:" in out
    assert "Wall Time/Task:" in out
    assert "Cost/Task:" in out
    assert "Review Rejection:" in out
    assert "Token Efficiency:" in out
    assert "Data Quality Warnings:" in out
    assert "=== Action Items (1) ===" in out
    assert "Review cost: $2.5000" in out
    assert "Report: ~/.agentforce/reviews/mission-123_review.json" in out


def test_api_get_review_returns_404_when_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("agentforce.server.handler.AGENTFORCE_HOME", tmp_path / ".agentforce")
    handler = _make_handler("/api/mission/mission-123/review")

    handler.do_GET()

    assert handler.send_response.call_args.args == (404,)
    assert _response_body(handler)["error"] == "No review found. POST to /api/mission/{id}/review to generate."


def test_api_get_review_returns_json_when_file_exists(tmp_path: Path, monkeypatch):
    home = tmp_path / ".agentforce"
    reviews_dir = home / "reviews"
    reviews_dir.mkdir(parents=True)
    monkeypatch.setattr("agentforce.server.handler.AGENTFORCE_HOME", home)
    review_file = reviews_dir / "mission-123_review.json"
    review_file.write_text(json.dumps({"mission_id": "mission-123", "summary": "ok"}))

    handler = _make_handler("/api/mission/mission-123/review")
    handler.do_GET()

    assert handler.send_response.call_args.args == (200,)
    assert _response_body(handler)["mission_id"] == "mission-123"


def test_api_get_review_returns_skipped_when_sentinel_exists(tmp_path: Path, monkeypatch):
    home = tmp_path / ".agentforce"
    reviews_dir = home / "reviews"
    reviews_dir.mkdir(parents=True)
    monkeypatch.setattr("agentforce.server.handler.AGENTFORCE_HOME", home)
    (reviews_dir / "mission-123_skipped").touch()

    handler = _make_handler("/api/mission/mission-123/review")
    handler.do_GET()

    assert handler.send_response.call_args.args == (200,)
    assert _response_body(handler) == {"skipped": True, "mission_id": "mission-123"}


def test_api_post_review_returns_404_when_mission_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("agentforce.server.handler.AGENTFORCE_HOME", tmp_path / ".agentforce")
    monkeypatch.setattr("agentforce.server.handler.STATE_DIR", tmp_path / "state")

    payload = json.dumps({"model": "claude"}).encode("utf-8")
    handler = _make_handler("/api/mission/mission-123/review", body=payload)

    handler.do_POST()

    assert handler.send_response.call_args.args == (404,)
    assert _response_body(handler)["error"] == "Mission 'mission-123' not found"


def test_api_post_review_returns_429_when_too_recent(tmp_path: Path, monkeypatch):
    home = tmp_path / ".agentforce"
    reviews_dir = home / "reviews"
    state_dir = tmp_path / "state"
    reviews_dir.mkdir(parents=True)
    state_dir.mkdir(parents=True)
    _make_state().save(state_dir / "mission-123.json")
    review_file = reviews_dir / "mission-123_review.json"
    review_file.write_text(json.dumps({"mission_id": "mission-123"}))
    monkeypatch.setattr("agentforce.server.handler.AGENTFORCE_HOME", home)
    monkeypatch.setattr("agentforce.server.handler.STATE_DIR", state_dir)

    payload = json.dumps({"model": "claude"}).encode("utf-8")
    handler = _make_handler("/api/mission/mission-123/review", body=payload)

    handler.do_POST()

    assert handler.send_response.call_args.args == (429,)
    assert "Review too recent" in _response_body(handler)["error"]


def test_api_post_review_returns_403_when_globally_disabled(tmp_path: Path, monkeypatch):
    home = tmp_path / ".agentforce"
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    _make_state().save(state_dir / "mission-123.json")
    monkeypatch.setattr("agentforce.server.handler.AGENTFORCE_HOME", home)
    monkeypatch.setattr("agentforce.server.handler.STATE_DIR", state_dir)
    monkeypatch.setattr("agentforce.review.config.AGENTFORCE_HOME", home)
    (home / "config.json").parent.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(json.dumps({"review_enabled": False}))

    payload = json.dumps({"model": "claude"}).encode("utf-8")
    handler = _make_handler("/api/mission/mission-123/review", body=payload)

    handler.do_POST()

    assert handler.send_response.call_args.args == (403,)
    assert _response_body(handler)["error"] == "Review disabled globally"


def test_api_post_review_skip_writes_sentinel_file(tmp_path: Path, monkeypatch):
    home = tmp_path / ".agentforce"
    reviews_dir = home / "reviews"
    state_dir = tmp_path / "state"
    reviews_dir.mkdir(parents=True)
    state_dir.mkdir(parents=True)
    _make_state().save(state_dir / "mission-123.json")
    monkeypatch.setattr("agentforce.server.handler.AGENTFORCE_HOME", home)
    monkeypatch.setattr("agentforce.server.handler.STATE_DIR", state_dir)

    payload = json.dumps({"skip": True}).encode("utf-8")
    handler = _make_handler("/api/mission/mission-123/review", body=payload)

    handler.do_POST()

    assert handler.send_response.call_args.args == (200,)
    assert _response_body(handler) == {"skipped": True}
    assert (reviews_dir / "mission-123_skipped").exists()
